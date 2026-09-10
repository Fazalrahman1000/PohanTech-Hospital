from django.test import TestCase
from django.core.cache import cache
from rest_framework.test import APIClient
from clinic.models import User

class LoginIdentifiers(TestCase):
    def setUp(self):
        cache.clear()
        self.user=User.objects.create_user(username='ClinicAdmin',email='Admin@clinic.test',password='Correct!Pass582',approved=True)
        self.client=APIClient()

    def test_email_independent_of_username(self):
        response=self.client.post('/api/auth/login/',{'email':' admin@CLINIC.test ','password':'Correct!Pass582'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.data['user']['id'],self.user.pk)

    def test_exact_username_and_legacy_field(self):
        for field in ['identifier','username','email']:
            with self.subTest(field=field):
                response=self.client.post('/api/auth/login/',{field:'ClinicAdmin','password':'Correct!Pass582'})
                self.assertEqual(response.status_code,200)

    def test_wrong_password_and_inactive_denied(self):
        self.assertEqual(self.client.post('/api/auth/login/',{'identifier':'ClinicAdmin','password':'wrong'}).status_code,400)
        self.user.is_active=False;self.user.save()
        self.assertEqual(self.client.post('/api/auth/login/',{'identifier':'ClinicAdmin','password':'Correct!Pass582'}).status_code,400)

    def test_approval_still_required(self):
        self.user.approved=False;self.user.save()
        self.assertEqual(self.client.post('/api/auth/login/',{'identifier':'admin@clinic.test','password':'Correct!Pass582'}).status_code,403)

    def test_ambiguous_identifier_fails_closed(self):
        User.objects.create_user(username='Admin@clinic.test',email='other@clinic.test',password='Other!Pass582',approved=True)
        self.assertEqual(self.client.post('/api/auth/login/',{'identifier':'Admin@clinic.test','password':'Correct!Pass582'}).status_code,400)

    def test_unknown_identifier_denied(self):
        self.assertEqual(self.client.post('/api/auth/login/',{'identifier':'unknown','password':'Correct!Pass582'}).status_code,400)
