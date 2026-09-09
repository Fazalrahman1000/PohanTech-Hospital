from dataclasses import dataclass
import hashlib
from rest_framework.exceptions import PermissionDenied, NotFound
from clinic.models import Patient, Doctor

@dataclass(frozen=True)
class Context:
    actor_id:int
    is_admin:bool
    doctor_id:int|None

    def patients(self):
        rows=Patient.objects.all()
        return rows if self.is_admin else rows.filter(doctor_id=self.doctor_id)

    def patient(self,pk):
        try: return self.patients().select_related('service','doctor').get(pk=pk)
        except Patient.DoesNotExist: raise NotFound('Patient is unavailable in your AI scope.')

    def require_admin(self):
        if not self.is_admin: raise PermissionDenied('Administrator role required for this AI tool.')

    def fingerprint(self):
        # Reassignment invalidates existing context so old patient data is not reused.
        ids=list(self.patients().order_by('pk').values_list('pk',flat=True))
        return hashlib.sha256(f'{self.actor_id}:{self.is_admin}:{self.doctor_id}:{ids}'.encode()).hexdigest()

def from_session(user):
    if not user.is_authenticated or not user.is_active or not (user.approved or user.is_superuser):
        raise PermissionDenied('Approved doctor or administrator session required.')
    is_admin=user.is_superuser or user.role=='admin'
    if not is_admin and user.role!='doctor': raise PermissionDenied('The AI workspace is restricted to doctors and administrators.')
    doctor_id=Doctor.objects.filter(user_id=user.pk).values_list('pk',flat=True).first()
    if not is_admin and not doctor_id: raise PermissionDenied('A doctor profile is required.')
    # No username, email, password hash, cookie, session key, or auth implementation is passed on.
    return Context(user.pk,is_admin,doctor_id)
