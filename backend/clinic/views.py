import calendar
from datetime import date,timedelta
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape
from django.conf import settings
from django.contrib.auth import authenticate,login,logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction,IntegrityError
from django.db.models import Sum,Count,F
from django.http import FileResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator
from rest_framework import viewsets,permissions,status,serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import *
from .serializers import *

def admin(u): return u.is_superuser or u.role=='admin'
class Approved(permissions.BasePermission):
    def has_permission(self,request,view): return request.user.is_authenticated and (request.user.approved or request.user.is_superuser)
class Clinical(Approved):
    def has_permission(self,r,v): return super().has_permission(r,v) and (r.method in permissions.SAFE_METHODS or admin(r.user) or r.user.role=='doctor')
class AdminWrite(Approved):
    def has_permission(self,r,v): return super().has_permission(r,v) and (r.method in permissions.SAFE_METHODS or admin(r.user))

def identity(u): return {'id':u.id,'name':u.first_name or u.username,'email':u.email,'role':'admin' if admin(u) else u.role,'approved':u.approved or u.is_superuser}

@method_decorator(csrf_protect,name='dispatch')
class Auth(APIView):
    permission_classes=[permissions.AllowAny]
    def get(self,r,action):
        return Response({'csrfToken':get_token(r),'user':identity(r.user) if r.user.is_authenticated else None,'googleClientId':settings.GOOGLE_CLIENT_ID})
    def post(self,r,action):
        if action=='logout': logout(r); return Response({'ok':True})
        email=str(r.data.get('email','')).strip().lower()
        password=r.data.get('password','')
        if action=='register':
            s=serializers.EmailField(); email=s.run_validation(email)
            name=serializers.CharField(max_length=150).run_validation(r.data.get('name'))
            try: validate_password(password,User(username=email,email=email,first_name=name))
            except DjangoValidationError as e: return Response({'detail':e.messages},status=400)
            try: User.objects.create_user(username=email,email=email,password=password,first_name=name)
            except IntegrityError: return Response({'detail':'This email is already registered.'},status=400)
            return Response({'detail':'Account created. Ask your administrator to approve access.'},status=201)
        if action=='google':
            if not settings.GOOGLE_CLIENT_ID: return Response({'detail':'Google sign-in is not configured.'},status=503)
            from google.oauth2 import id_token
            from google.auth.transport.requests import Request
            try:
                info=id_token.verify_oauth2_token(r.data.get('credential',''),Request(),settings.GOOGLE_CLIENT_ID)
                if not info.get('email_verified'): raise ValueError()
            except Exception: return Response({'detail':'Google identity could not be verified.'},status=400)
            u=User.objects.filter(google_sub=info['sub']).first()
            if not u:
                email=info['email'].lower()
                if User.objects.filter(email=email).exists(): return Response({'detail':'Use your existing email login. Automatic account linking is disabled.'},status=409)
                u=User.objects.create_user(username=email,email=email,first_name=info.get('name',''),google_sub=info['sub'])
        elif action=='login': u=authenticate(r,username=email,password=password)
        else: return Response(status=404)
        if not u or not u.is_active: return Response({'detail':'Invalid login details.'},status=400)
        if not (u.approved or u.is_superuser): return Response({'detail':'Your account is waiting for administrator approval.'},status=403)
        login(r,u); return Response({'user':identity(u),'csrfToken':get_token(r)})

class Base(viewsets.ModelViewSet):
    permission_classes=[Approved]
    http_method_names=['get','post','head','options']
class Doctors(Base):
    queryset=Doctor.objects.select_related('user').order_by('name'); serializer_class=DoctorSerializer; permission_classes=[AdminWrite]
    @action(detail=True,methods=['post'])
    def availability(self,r,pk=None):
        d=self.get_object(); d.available=not d.available; d.save(update_fields=['available']); return Response(self.get_serializer(d).data)
class Patients(Base):
    queryset=Patient.objects.select_related('service','doctor').order_by('-registered_at'); serializer_class=PatientSerializer
class Services(Base):
    queryset=Service.objects.order_by('name'); serializer_class=ServiceSerializer; permission_classes=[AdminWrite]
class Drugs(Base):
    queryset=Drug.objects.order_by('expiry_date'); serializer_class=DrugSerializer; permission_classes=[AdminWrite]
    @transaction.atomic
    def perform_create(self,s):
        d=s.save(); StockLog.objects.create(drug=d,change=d.quantity,reason='Initial batch received',actor=self.request.user)
    @action(detail=True,methods=['post'])
    @transaction.atomic
    def restock(self,r,pk=None):
        d=self.get_object()
        if d.expiry_date<=timezone.localdate(): raise serializers.ValidationError('Cannot restock an expired batch. Add a new batch.')
        q=serializers.IntegerField(min_value=1).run_validation(r.data.get('quantity'))
        Drug.objects.filter(pk=d.pk).update(quantity=F('quantity')+q)
        StockLog.objects.create(drug=d,change=q,reason='Batch restocked',actor=r.user)
        d.refresh_from_db(); return Response(self.get_serializer(d).data)
class Prescriptions(Base):
    queryset=Prescription.objects.select_related('patient','doctor').prefetch_related('items__drug').order_by('-created_at'); serializer_class=PrescriptionSerializer; permission_classes=[Clinical]
    def perform_create(self,s): s.save(created_by=self.request.user)
class Payments(Base):
    queryset=Payment.objects.select_related('patient').order_by('-created_at'); serializer_class=PaymentSerializer
    def perform_create(self,s): s.save(created_by=self.request.user)
class StockLogs(Base):
    queryset=StockLog.objects.select_related('drug').order_by('-created_at'); serializer_class=StockLogSerializer; http_method_names=['get','head','options']
class Posts(Base):
    queryset=Post.objects.select_related('author').prefetch_related('comments__author','likes').order_by('-created_at'); serializer_class=PostSerializer
    def perform_create(self,s): s.save(author=self.request.user)
    @action(detail=True,methods=['post'])
    def like(self,r,pk=None):
        p=self.get_object()
        if p.likes.filter(pk=r.user.pk).exists(): p.likes.remove(r.user)
        else: p.likes.add(r.user)
        return Response(self.get_serializer(p).data)
    @action(detail=True,methods=['post'])
    def comment(self,r,pk=None):
        s=CommentSerializer(data=r.data); s.is_valid(raise_exception=True); s.save(post=self.get_object(),author=r.user); return Response(s.data,status=201)

def period(r):
    today=timezone.localdate()
    try:
        year=int(r.query_params.get('year',today.year)); month=int(r.query_params.get('month',today.month))
        start=date(year,month,1) if r.query_params.get('period','month')=='month' else date(year,1,1)
        end=(date(year+1,1,1) if month==12 else date(year,month+1,1)) if r.query_params.get('period','month')=='month' else date(year+1,1,1)
    except (ValueError,OverflowError): raise serializers.ValidationError('Invalid reporting period.')
    return start,end
class Dashboard(APIView):
    permission_classes=[Approved]
    def get(self,r):
        today=timezone.localdate(); start,end=period(r)
        patients=Patient.objects.filter(registered_at__date__gte=start,registered_at__date__lt=end)
        payments=Payment.objects.filter(created_at__date__gte=start,created_at__date__lt=end)
        week=today-timedelta(days=today.weekday())
        trend=[{'label':calendar.month_abbr[m],'count':Patient.objects.filter(registered_at__year=start.year,registered_at__month=m).count()} for m in range(1,13)]
        return Response({'patients':patients.count(),'week':Patient.objects.filter(registered_at__date__gte=week).count(),'month':Patient.objects.filter(registered_at__year=today.year,registered_at__month=today.month).count(),'year':Patient.objects.filter(registered_at__year=today.year).count(),'doctors':Doctor.objects.filter(available=True).count(),'revenue':payments.aggregate(total=Sum('amount'))['total'] or 0,'payments':payments.count(),'services':[{'id':s.id,'name':s.name,'count':patients.filter(service=s).count()} for s in Service.objects.filter(active=True)],'trend':trend,'low_stock':Drug.objects.filter(quantity__lt=20).count(),'expired':Drug.objects.filter(expiry_date__lte=today).count()})

class Accounts(APIView):
    permission_classes=[Approved]
    def get(self,r):
        if not admin(r.user): return Response(status=403)
        return Response([identity(u) for u in User.objects.filter(approved=False,is_superuser=False)])
    def post(self,r):
        if not admin(r.user): return Response(status=403)
        try: u=User.objects.get(pk=r.data.get('id'))
        except (User.DoesNotExist,ValueError): return Response(status=404)
        u.approved=True; u.save(update_fields=['approved']); return Response(identity(u))

class Report(APIView):
    permission_classes=[Approved]
    def get(self,r):
        from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        start,end=period(r); kind=r.query_params.get('kind','summary')
        buf=BytesIO(); styles=getSampleStyleSheet(); story=[Paragraph('MEDORA | Clinic report',styles['Title']),Paragraph(f'{kind.title()} • {start} to {end-timedelta(days=1)}',styles['Normal']),Spacer(1,20)]
        def p(v): return Paragraph(escape(str(v)),styles['Normal'])
        if kind=='drugs':
            rows=[['Drug / batch','Type','On hand now','Expiry']]+[[p(f'{d.name} / {d.batch}'),d.type,str(d.quantity),str(d.expiry_date)] for d in Drug.objects.all()]
            story.append(Paragraph('Current inventory snapshot; movements below are filtered to the selected period.',styles['Normal']))
            movements=StockLog.objects.filter(created_at__date__gte=start,created_at__date__lt=end).select_related('drug')
        elif kind=='prescriptions':
            rows=[['Date','Patient','Doctor','Diagnosis']]+[[str(x.created_at.date()),p(x.patient.name),p(x.doctor.name),p(x.diagnosis)] for x in Prescription.objects.filter(created_at__date__gte=start,created_at__date__lt=end).select_related('patient','doctor')]
        else:
            ps=Payment.objects.filter(created_at__date__gte=start,created_at__date__lt=end).select_related('patient')
            n=Patient.objects.filter(registered_at__date__gte=start,registered_at__date__lt=end).count()
            story += [Paragraph(f'Patients registered: {n}',styles['Heading2']),Paragraph(f'Received: {ps.aggregate(t=Sum("amount"))["t"] or 0} (clinic currency)',styles['Heading2'])]
            rows=[['Date','Patient','Received','Note']]+[[str(x.created_at.date()),p(x.patient.name),str(x.amount),p(x.note)] for x in ps]
        def table(rows):
            t=Table(rows,colWidths=[120,130,110,135],repeatRows=1); t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#116b5b')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('VALIGN',(0,0),(-1,-1),'TOP'),('BOTTOMPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),10),('LINEBELOW',(0,0),(-1,-1),0.4,colors.lightgrey)])); return t
        story.append(table(rows))
        if kind=='drugs': story += [Spacer(1,20),Paragraph('Stock movement ledger',styles['Heading2']),table([['Date','Drug','Change','Reason']]+[[str(x.created_at.date()),p(x.drug.name),str(x.change),p(x.reason)] for x in movements])]
        SimpleDocTemplate(buf,title='Medora clinic report').build(story); buf.seek(0)
        return FileResponse(buf,as_attachment=True,filename=f'medora-{kind}-{start}.pdf')
