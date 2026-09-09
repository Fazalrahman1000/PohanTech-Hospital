from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from .models import *
class Workflows(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user(username='admin@test.com',email='admin@test.com',password='Strong!Test891',role='admin',approved=True)
        self.staff=User.objects.create_user(username='staff@test.com',email='staff@test.com',role='staff',approved=True)
        self.doctor_user=User.objects.create_user(username='doc@test.com',email='doc@test.com',role='doctor',approved=True)
        self.doctor=Doctor.objects.create(user=self.doctor_user,name='Doctor',father_name='Parent',age=30,specialization='General',experience=5)
        self.service=Service.objects.create(name='General')
        self.patient=Patient.objects.create(name='Patient',father_name='Parent',province='A',district='B',id_card='123',phone='0700',illness='Test',service=self.service)
        self.drug=Drug.objects.create(name='Test drug',batch='B1',type='Tablet',included_at=timezone.localdate(),production_date=timezone.localdate()-timedelta(days=30),expiry_date=timezone.localdate()+timedelta(days=30),quantity=10)
        self.c=APIClient(); self.c.force_authenticate(self.admin)
    def payload(self,q=3): return {'patient':self.patient.id,'doctor':self.doctor.id,'diagnosis':'Test diagnosis','instructions':'Test instructions','items':[{'drug':self.drug.id,'quantity':q,'dosage':'Test dosage'}]}
    def test_dispense_and_ledger(self):
        r=self.c.post('/api/prescriptions/',self.payload(),format='json'); self.assertEqual(r.status_code,201,r.data)
        self.drug.refresh_from_db(); self.assertEqual(self.drug.quantity,7); self.assertEqual(StockLog.objects.get().change,-3)
    def test_insufficient_stock_rolls_back_all(self):
        r=self.c.post('/api/prescriptions/',self.payload(11),format='json'); self.assertEqual(r.status_code,400)
        self.drug.refresh_from_db(); self.assertEqual(self.drug.quantity,10); self.assertEqual(Prescription.objects.count(),0); self.assertEqual(StockLog.objects.count(),0)
    def test_multiple_items_rollback(self):
        other=Drug.objects.create(name='Other',batch='B2',type='Syrup',included_at=self.drug.included_at,production_date=self.drug.production_date,expiry_date=self.drug.expiry_date,quantity=1)
        p=self.payload(); p['items'].append({'drug':other.id,'quantity':2,'dosage':'Test'})
        self.assertEqual(self.c.post('/api/prescriptions/',p,format='json').status_code,400)
        self.drug.refresh_from_db(); self.assertEqual(self.drug.quantity,10); self.assertFalse(Prescription.objects.exists())
    def test_expired_and_duplicate_rejected(self):
        p=self.payload(); p['items']*=2
        self.assertEqual(self.c.post('/api/prescriptions/',p,format='json').status_code,400)
        self.drug.expiry_date=timezone.localdate(); self.drug.save()
        self.assertEqual(self.c.post('/api/prescriptions/',self.payload(),format='json').status_code,400)
    def test_staff_cannot_prescribe_or_add_doctor(self):
        self.c.force_authenticate(self.staff)
        self.assertEqual(self.c.post('/api/prescriptions/',self.payload(),format='json').status_code,403)
        self.assertEqual(self.c.post('/api/doctors/',{},format='json').status_code,403)
    def test_pending_blocked_and_cannot_self_approve(self):
        self.staff.approved=False; self.staff.save(); self.c.force_authenticate(self.staff)
        self.assertEqual(self.c.get('/api/patients/').status_code,403)
        self.assertEqual(self.c.post('/api/accounts/',{'id':self.staff.pk},format='json').status_code,403)
    def test_payments_and_periods(self):
        self.assertEqual(self.c.post('/api/payments/',{'patient':self.patient.id,'amount':'-1'},format='json').status_code,400)
        self.assertEqual(self.c.post('/api/payments/',{'patient':self.patient.id,'amount':'125.25'},format='json').status_code,201)
        self.assertEqual(str(self.c.get('/api/dashboard/').data['revenue']),'125.25')
        self.assertEqual(self.c.get('/api/dashboard/?year=2020').data['revenue'],0)
    def test_restock_and_pdf(self):
        self.assertEqual(self.c.post(f'/api/drugs/{self.drug.pk}/restock/',{'quantity':5},format='json').status_code,200)
        self.drug.refresh_from_db(); self.assertEqual(self.drug.quantity,15)
        for kind in ['summary','drugs','prescriptions']:
            r=self.c.get('/api/reports/?kind='+kind); self.assertEqual(r.status_code,200); self.assertTrue(b''.join(r.streaming_content).startswith(b'%PDF'))
    def test_likes_toggle_comments(self):
        p=self.c.post('/api/posts/',{'body':'Hello'},format='json').data
        self.assertEqual(self.c.post(f'/api/posts/{p["id"]}/like/').data['like_count'],1)
        self.assertEqual(self.c.post(f'/api/posts/{p["id"]}/like/').data['like_count'],0)
        self.assertEqual(self.c.post(f'/api/posts/{p["id"]}/comment/',{'body':'Reply'},format='json').status_code,201)
    def test_csrf_login_and_registration(self):
        c=APIClient(enforce_csrf_checks=True)
        self.assertEqual(c.post('/api/auth/login/',{'email':'admin@test.com','password':'Strong!Test891'}).status_code,403)
        csrf=c.get('/api/auth/session/').data['csrfToken']
        r=c.post('/api/auth/login/',{'email':'admin@test.com','password':'Strong!Test891'},HTTP_X_CSRFTOKEN=csrf); self.assertEqual(r.status_code,200)
    def test_registration_ignores_role(self):
        c=APIClient(); r=c.post('/api/auth/register/',{'email':'new@test.com','name':'New User','password':'Strong!New891','role':'admin','approved':True},format='json')
        self.assertEqual(r.status_code,201,r.data); u=User.objects.get(email='new@test.com'); self.assertEqual(u.role,'staff'); self.assertFalse(u.approved)
    def test_local_browser_origins_can_login(self):
        for host in ['localhost', '127.0.0.1']:
            for port in [5173, 5174]:
                with self.subTest(host=host, port=port):
                    c=APIClient(enforce_csrf_checks=True)
                    token=c.get('/api/auth/session/').data['csrfToken']
                    response=c.post('/api/auth/login/',
                        {'email':'admin@test.com','password':'Strong!Test891'},
                        HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN=f'http://{host}:{port}')
                    self.assertEqual(response.status_code,200)
    def test_untrusted_origin_still_rejected(self):
        c=APIClient(enforce_csrf_checks=True)
        token=c.get('/api/auth/session/').data['csrfToken']
        response=c.post('/api/auth/login/',
            {'email':'admin@test.com','password':'Strong!Test891'},
            HTTP_X_CSRFTOKEN=token,HTTP_ORIGIN='https://untrusted.example')
        self.assertEqual(response.status_code,403)
    def test_single_prescription_pdf_and_no_repeat_dispensing(self):
        prescription=self.c.post('/api/prescriptions/',self.payload(),format='json').data
        self.c.force_authenticate(self.staff)
        for _ in range(2):
            response=self.c.get(f'/api/prescriptions/{prescription["id"]}/pdf/')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response['Content-Type'],'application/pdf')
            self.assertIn('inline',response['Content-Disposition'])
            self.assertEqual(response['Cache-Control'],'private, no-store')
            self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.quantity,7)
        self.assertEqual(StockLog.objects.count(),1)
        self.assertEqual(self.c.get('/api/prescriptions/999999/pdf/').status_code,404)
    def test_prescription_pdf_requires_approved_login(self):
        prescription=self.c.post('/api/prescriptions/',self.payload(),format='json').data
        url=f'/api/prescriptions/{prescription["id"]}/pdf/'
        self.c.force_authenticate(None)
        self.assertEqual(self.c.get(url).status_code,403)
        self.staff.approved=False; self.staff.save()
        self.c.force_authenticate(self.staff)
        self.assertEqual(self.c.get(url).status_code,403)
