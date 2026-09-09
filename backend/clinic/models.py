from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from decimal import Decimal

class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=12, choices=[('admin','Admin'),('doctor','Doctor'),('staff','Staff')], default='staff')
    approved = models.BooleanField(default=False)
    google_sub = models.CharField(max_length=255,unique=True,null=True,blank=True)

class Doctor(models.Model):
    user = models.OneToOneField(User,on_delete=models.PROTECT,related_name='doctor_profile')
    name = models.CharField(max_length=160)
    father_name = models.CharField(max_length=160)
    age = models.PositiveIntegerField(validators=[MinValueValidator(18)])
    specialization = models.CharField(max_length=160)
    experience = models.PositiveIntegerField(default=0)
    available = models.BooleanField(default=True)

class Service(models.Model):
    name = models.CharField(max_length=120,unique=True)
    active = models.BooleanField(default=True)

class Patient(models.Model):
    name = models.CharField(max_length=160)
    father_name = models.CharField(max_length=160)
    province = models.CharField(max_length=100)
    district = models.CharField(max_length=100)
    id_card = models.CharField(max_length=80,unique=True)
    phone = models.CharField(max_length=30)
    illness = models.TextField()
    visit_type = models.CharField(max_length=20,choices=[('OPD','OPD'),('IPD','IPD'),('Emergency','Emergency'),('Other','Other')],default='OPD')
    service = models.ForeignKey(Service,on_delete=models.PROTECT)
    doctor = models.ForeignKey(Doctor,on_delete=models.PROTECT,null=True,blank=True)
    registered_at = models.DateTimeField(auto_now_add=True)

class Drug(models.Model):
    name = models.CharField(max_length=160)
    batch = models.CharField(max_length=80,unique=True)
    type = models.CharField(max_length=20,choices=[(x,x) for x in ['Tablet','Syrup','Capsule','Injection','Other']])
    included_at = models.DateField()
    production_date = models.DateField()
    expiry_date = models.DateField()
    quantity = models.PositiveIntegerField(default=0)

class Prescription(models.Model):
    patient = models.ForeignKey(Patient,on_delete=models.PROTECT)
    doctor = models.ForeignKey(Doctor,on_delete=models.PROTECT)
    diagnosis = models.TextField()
    instructions = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User,on_delete=models.PROTECT)

class PrescriptionItem(models.Model):
    prescription = models.ForeignKey(Prescription,on_delete=models.PROTECT,related_name='items')
    drug = models.ForeignKey(Drug,on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    dosage = models.CharField(max_length=250)

class StockLog(models.Model):
    drug = models.ForeignKey(Drug,on_delete=models.PROTECT)
    change = models.IntegerField()
    reason = models.CharField(max_length=200)
    prescription = models.ForeignKey(Prescription,on_delete=models.PROTECT,null=True)
    actor = models.ForeignKey(User,on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

class Payment(models.Model):
    patient = models.ForeignKey(Patient,on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12,decimal_places=2,validators=[MinValueValidator(Decimal('0.01'))])
    note = models.CharField(max_length=250,blank=True)
    created_by = models.ForeignKey(User,on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

class Post(models.Model):
    author = models.ForeignKey(User,on_delete=models.PROTECT)
    body = models.TextField(max_length=5000)
    created_at = models.DateTimeField(auto_now_add=True)
    likes = models.ManyToManyField(User,related_name='liked_posts',blank=True)

class Comment(models.Model):
    post = models.ForeignKey(Post,on_delete=models.CASCADE,related_name='comments')
    author = models.ForeignKey(User,on_delete=models.PROTECT)
    body = models.TextField(max_length=1500)
    created_at = models.DateTimeField(auto_now_add=True)

class AIConversation(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    scope = models.CharField(max_length=64)
    messages = models.JSONField(default=list)
    busy = models.BooleanField(default=False)
    busy_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class AIDraft(models.Model):
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='ai_drafts')
    kind = models.CharField(max_length=32)
    payload = models.JSONField()
    review = models.JSONField(default=dict)
    doctor = models.ForeignKey(Doctor, on_delete=models.PROTECT, null=True)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, null=True)
    status = models.CharField(max_length=12, default='pending', choices=[('pending','Pending'),('approved','Approved'),('rejected','Rejected')])
    approved_by = models.ForeignKey(User, on_delete=models.PROTECT, null=True, related_name='ai_approvals')
    result_id = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class AIAudit(models.Model):
    actor = models.ForeignKey(User, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    outcome = models.CharField(max_length=24)
    # Identifiers only; no chat text, tool arguments, patient names, or credentials.
    draft = models.ForeignKey(AIDraft, on_delete=models.PROTECT, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class AIContentFlag(models.Model):
    post = models.ForeignKey(Post, on_delete=models.PROTECT)
    reason = models.CharField(max_length=500)
    reviewed_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
