import os
from datetime import timedelta
from django.core.management.base import BaseCommand,CommandError
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from clinic.models import *
class Command(BaseCommand):
    help='Create fictional local demo records. Requires DEBUG=1 and DEMO_PASSWORD.'
    @transaction.atomic
    def handle(self,*args,**kwargs):
        if not settings.DEBUG or not os.getenv('DEMO_PASSWORD'): raise CommandError('Set DEBUG=1 and DEMO_PASSWORD first.')
        if User.objects.filter(email='admin@medora.local').exists(): self.stdout.write('Demo already exists.'); return
        u=User.objects.create_superuser(username='admin@medora.local',email='admin@medora.local',password=os.environ['DEMO_PASSWORD'],first_name='Clinic Admin',role='admin',approved=True)
        services=[Service.objects.get_or_create(name=n)[0] for n in ['General medicine','Cardiology','Pediatrics','Dental care']]
        doctors=[]
        for i,(name,specialty) in enumerate([('Dr. Sara Rahimi','General medicine'),('Dr. Ahmad Noor','Cardiology'),('Dr. Laila Azizi','Pediatrics')]):
            du=User.objects.create_user(username=f'doctor{i}@medora.local',email=f'doctor{i}@medora.local',password=os.environ['DEMO_PASSWORD'],first_name=name,role='doctor',approved=True)
            doctors.append(Doctor.objects.create(user=du,name=name,father_name='Demo parent',age=32+i*5,specialization=specialty,experience=7+i*3))
        now=timezone.now()
        for i in range(32):
            p=Patient.objects.create(name=['Amina','Omar','Maryam','Yusuf','Zahra','Farid','Nadia','Bilal'][i%8]+f' Demo {i+1}',father_name='Fictional parent',province='Demo province',district='Central district',id_card=f'DEMO-{i+1:04}',phone=f'070000{i:04}',illness='Fictional demonstration record',service=services[i%4],doctor=doctors[i%3],visit_type=['OPD','OPD','IPD','Emergency'][i%4])
            dt=now-timedelta(days=0 if i<5 else i*3)
            Patient.objects.filter(pk=p.pk).update(registered_at=dt)
            pay=Payment.objects.create(patient=p,amount=250+i*10,note='Fictional demo payment',created_by=u)
            Payment.objects.filter(pk=pay.pk).update(created_at=dt)
        for i,(n,t,q) in enumerate([('Paracetamol 500 mg','Tablet',240),('Amoxicillin 250 mg','Capsule',120),('Cetirizine','Syrup',16),('Saline 0.9%','Injection',80)]):
            d=Drug.objects.create(name=n,type=t,batch=f'DEMO-B{i+1}',included_at=now.date(),production_date=now.date()-timedelta(days=60),expiry_date=now.date()+timedelta(days=365),quantity=q)
            StockLog.objects.create(drug=d,change=q,reason='Fictional demo stock',actor=u)
        Post.objects.create(author=u,body='Welcome to the Medora demo workspace. All records here are fictional. Start by registering a patient or reviewing the drug store.')
        self.stdout.write('Fictional demo created. Login: admin@medora.local with your DEMO_PASSWORD.')
