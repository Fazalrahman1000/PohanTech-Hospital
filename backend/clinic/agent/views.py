import hashlib,json
from datetime import timedelta
from django.core import signing
from django.db import transaction
from django.db.models import Q,F
from django.http import FileResponse
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.exceptions import ValidationError,PermissionDenied,NotFound
from clinic.models import AIConversation,AIDraft,AIAudit,AIContentFlag,Doctor,Drug,StockLog,Prescription
from clinic.serializers import PrescriptionSerializer,PaymentSerializer
from .context import from_session
from . import provider,runner
from .tools import stock_check

class Access(BasePermission):
    def has_permission(self,request,view):
        from_session(request.user)
        return True

class ChatThrottle(SimpleRateThrottle):
    rate='6/min'
    def get_cache_key(self,request,view): return f'ai-chat:{request.user.pk}'

class PrivateAPI(APIView):
    permission_classes=[Access]
    def finalize_response(self,*args,**kwargs):
        response=super().finalize_response(*args,**kwargs)
        response['Cache-Control']='private, no-store'
        return response

class Status(PrivateAPI):
    def get(self,r):
        ctx=from_session(r.user)
        return Response({**provider.status(),'doctor_id':ctx.doctor_id,'scope':'clinic' if ctx.is_admin else 'assigned patients',
            'privacy':'Local inference only. No cloud fallback. Chat history is stored in the clinic database until cleared.'})

class Chat(PrivateAPI):
    throttle_classes=[ChatThrottle]
    def post(self,r):
        if set(r.data)-{'message','conversation_id'}: raise ValidationError('Only message and conversation_id are accepted.')
        message=r.data.get('message')
        if not isinstance(message,str) or not 1<=len(message.strip())<=4000: raise ValidationError('Message must contain 1-4000 characters.')
        ctx=from_session(r.user); scope=ctx.fingerprint()
        pk=r.data.get('conversation_id')
        if pk is None: conversation=AIConversation.objects.create(owner_id=ctx.actor_id,scope=scope)
        else:
            if type(pk) is not int: raise ValidationError('Invalid conversation ID.')
            try: conversation=AIConversation.objects.get(pk=pk,owner_id=ctx.actor_id)
            except AIConversation.DoesNotExist: raise NotFound('Conversation unavailable.')
        if conversation.scope!=scope:
            AIConversation.objects.filter(pk=conversation.pk).update(messages=[],scope=scope)
            raise ValidationError('Patient access changed. Start a new conversation; previous context was cleared.')
        acquired=AIConversation.objects.filter(pk=conversation.pk).filter(Q(busy=False)|Q(busy_at__lt=timezone.now()-timedelta(minutes=15))).update(busy=True,busy_at=timezone.now())
        if not acquired: raise ValidationError('A reply is already running in this conversation.')
        try:
            result=runner.run(ctx,message,conversation.messages)
            r.user.refresh_from_db(fields=['role','approved','is_active','is_superuser'])
            if from_session(r.user).fingerprint()!=scope: raise PermissionDenied('Access changed during this request. Start a new conversation.')
            history=(conversation.messages+[{'role':'user','content':message},{'role':'assistant','content':result['answer']}])[-12:]
            AIConversation.objects.filter(pk=conversation.pk).update(messages=history)
            AIAudit.objects.create(actor_id=ctx.actor_id,action='chat',outcome='ok')
            return Response({**result,'conversation_id':conversation.pk})
        finally: AIConversation.objects.filter(pk=conversation.pk).update(busy=False)

class ClearConversation(PrivateAPI):
    def post(self,r,pk=None):
        rows=AIConversation.objects.filter(owner=r.user,busy=False)
        if pk is not None: rows=rows.filter(pk=pk)
        count,_=rows.delete()
        if pk is not None and not count: raise NotFound('Conversation unavailable or still running.')
        return Response({'cleared':True})

def visible_drafts(ctx):
    rows=AIDraft.objects.filter(Q(owner_id=ctx.actor_id)|Q(doctor_id=ctx.doctor_id) if ctx.doctor_id else Q(owner_id=ctx.actor_id))
    # Recheck current patient assignment, including drafts authored before reassignment.
    return rows.filter(Q(patient__isnull=True)|Q(patient__in=ctx.patients())).select_related('patient','doctor')

def approvable(ctx,draft):
    if draft.kind in ('prescription','payment'):
        return bool(ctx.doctor_id and draft.doctor_id==ctx.doctor_id and draft.patient and draft.patient.doctor_id==ctx.doctor_id)
    return ctx.is_admin and draft.owner_id==ctx.actor_id

def digest(draft):
    raw=json.dumps({'kind':draft.kind,'payload':draft.payload,'review':draft.review},sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()

class Drafts(PrivateAPI):
    def get(self,r):
        ctx=from_session(r.user)
        drafts=[]
        for d in visible_drafts(ctx).order_by('-created_at')[:50]:
            allowed=approvable(ctx,d) and d.status=='pending' and d.created_at>timezone.now()-timedelta(hours=24)
            token=signing.dumps({'draft':d.pk,'reviewer':ctx.actor_id,'digest':digest(d)},salt='ai-review') if allowed else None
            drafts.append({'id':d.pk,'kind':d.kind,'payload':d.payload,'review':d.review,'status':d.status,'result_id':d.result_id,
                'created_at':d.created_at,'can_approve':allowed,'review_token':token,
                'approval_rule':'Assigned doctor must review and approve.' if d.doctor_id else 'Creating administrator must review and approve.'})
        return Response(drafts)

class Review(PrivateAPI):
    @transaction.atomic
    def post(self,r,pk):
        if set(r.data)!={'decision','review_token','confirmed'} or r.data.get('confirmed') is not True:
            raise ValidationError('A separate confirmed human review click is required.')
        if r.data['decision'] not in ('approve','reject'): raise ValidationError('Invalid review decision.')
        ctx=from_session(r.user)
        try: d=visible_drafts(ctx).select_for_update().get(pk=pk)
        except AIDraft.DoesNotExist: raise NotFound('Draft unavailable.')
        if not approvable(ctx,d): raise PermissionDenied('Only the designated human reviewer may approve or reject this proposal.')
        try: token=signing.loads(r.data['review_token'],salt='ai-review',max_age=900)
        except (signing.BadSignature,TypeError): raise ValidationError('Review expired. Refresh the queue and review again.')
        if token!={'draft':d.pk,'reviewer':ctx.actor_id,'digest':digest(d)}: raise ValidationError('Review does not match this exact proposal.')
        if d.created_at<timezone.now()-timedelta(hours=24): raise ValidationError('Draft expired. Request a fresh proposal.')
        status='approved' if r.data['decision']=='approve' else 'rejected'
        if not AIDraft.objects.filter(pk=d.pk,status='pending').update(status=status,approved_by_id=ctx.actor_id):
            raise ValidationError('This proposal has already been reviewed.')
        result_id=None
        if status=='approved':
            if d.kind=='prescription':
                check=stock_check([{'drug_id':i['drug'],'quantity':i['quantity']} for i in d.payload['items']])
                if not check['all_available']: raise ValidationError({'detail':'Stock changed. No prescription was saved. Request a new draft.','inventory':check})
                serializer=PrescriptionSerializer(data=d.payload,context={'request':r})
                serializer.is_valid(raise_exception=True)
                result_id=serializer.save(created_by=r.user).pk
            elif d.kind=='payment':
                serializer=PaymentSerializer(data=d.payload,context={'request':r})
                serializer.is_valid(raise_exception=True)
                result_id=serializer.save(created_by=r.user).pk
            elif d.kind=='restock':
                drug=Drug.objects.select_for_update().get(pk=d.payload['drug_id'])
                if drug.expiry_date<=timezone.localdate() or drug.quantity!=d.review['previous_quantity']:
                    raise ValidationError('Batch changed or expired. Request a fresh restock proposal.')
                Drug.objects.filter(pk=drug.pk).update(quantity=F('quantity')+d.payload['quantity'])
                result_id=StockLog.objects.create(drug=drug,change=d.payload['quantity'],reason=d.payload['reason'],actor=r.user).pk
            elif d.kind=='availability':
                changed=Doctor.objects.filter(pk=d.payload['doctor_id'],available=d.review['previous_available']).update(available=d.payload['available'])
                if not changed: raise ValidationError('Doctor availability changed. Request a fresh proposal.')
                result_id=d.payload['doctor_id']
            elif d.kind=='content_flag':
                result_id=AIContentFlag.objects.create(post_id=d.payload['post_id'],reason=d.payload['reason'],reviewed_by=r.user).pk
            else: raise ValidationError('Unsupported proposal type.')
        AIDraft.objects.filter(pk=d.pk).update(result_id=result_id)
        AIAudit.objects.create(actor_id=ctx.actor_id,action='human_'+status,outcome='ok',draft=d)
        return Response({'id':d.pk,'status':status,'result_id':result_id})

class Audit(PrivateAPI):
    def get(self,r):
        ctx=from_session(r.user)
        rows=AIAudit.objects.all() if ctx.is_admin else AIAudit.objects.filter(actor_id=ctx.actor_id)
        flags=AIContentFlag.objects.order_by('-created_at').values('id','post_id','reason','created_at')[:30] if ctx.is_admin else []
        return Response({'events':list(rows.order_by('-created_at').values('id','action','outcome','draft_id','created_at')[:50]),'content_flags':list(flags)})

class PrescriptionCopy(PrivateAPI):
    def get(self,r,pk):
        from clinic.prescription_pdf import render_prescription
        ctx=from_session(r.user)
        try: rx=Prescription.objects.select_related('patient__service','doctor').prefetch_related('items__drug').get(pk=pk,patient__in=ctx.patients())
        except Prescription.DoesNotExist: raise NotFound('Prescription unavailable in your AI scope.')
        return FileResponse(render_prescription(rx),content_type='application/pdf',filename=f'prescription-RX-{rx.pk:04d}.pdf')
