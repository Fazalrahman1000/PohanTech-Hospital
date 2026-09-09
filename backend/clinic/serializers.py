from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone
from .models import *

class DoctorSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(write_only=True)
    password = serializers.CharField(write_only=True)
    class Meta:
        model=Doctor
        fields=['id','name','father_name','age','specialization','experience','available','email','password']
    def validate_email(self,value):
        value=value.lower()
        if User.objects.filter(email=value).exists(): raise serializers.ValidationError('Email already registered.')
        return value
    def validate_password(self,value):
        validate_password(value)
        return value
    @transaction.atomic
    def create(self,data):
        email=data.pop('email'); password=data.pop('password')
        user=User.objects.create_user(username=email,email=email,password=password,role='doctor',approved=True,first_name=data['name'])
        return Doctor.objects.create(user=user,**data)

class PatientSerializer(serializers.ModelSerializer):
    service_name=serializers.CharField(source='service.name',read_only=True)
    doctor_name=serializers.CharField(source='doctor.name',read_only=True)
    class Meta:
        model=Patient; fields='__all__'; read_only_fields=['registered_at']

class DrugSerializer(serializers.ModelSerializer):
    class Meta:
        model=Drug; fields='__all__'
    def validate(self,data):
        if data['production_date']>data['included_at']: raise serializers.ValidationError('Production must precede stock arrival.')
        if data['expiry_date']<=max(data['included_at'],timezone.localdate()): raise serializers.ValidationError('Expiry must be after arrival and today.')
        return data

class ItemSerializer(serializers.ModelSerializer):
    drug_name=serializers.CharField(source='drug.name',read_only=True)
    class Meta:
        model=PrescriptionItem; fields=['drug','drug_name','quantity','dosage']

class PrescriptionSerializer(serializers.ModelSerializer):
    items=ItemSerializer(many=True)
    patient_name=serializers.CharField(source='patient.name',read_only=True)
    doctor_name=serializers.CharField(source='doctor.name',read_only=True)
    class Meta:
        model=Prescription; fields='__all__'; read_only_fields=['created_by','created_at']
    def validate(self,data):
        if not data['items']: raise serializers.ValidationError('At least one drug is required.')
        ids=[x['drug'].pk for x in data['items']]
        if len(ids)!=len(set(ids)): raise serializers.ValidationError('Combine duplicate drug lines.')
        u=self.context['request'].user
        if u.role=='doctor' and data['doctor'].user_id!=u.id: raise serializers.ValidationError('Prescribe under your own profile.')
        return data
    @transaction.atomic
    def create(self,data):
        items=data.pop('items')
        drugs={d.pk:d for d in Drug.objects.select_for_update().filter(pk__in=[i['drug'].pk for i in items]).order_by('pk')}
        for item in items:
            drug=drugs[item['drug'].pk]
            if drug.expiry_date<=timezone.localdate(): raise serializers.ValidationError(f'{drug.name} is expired.')
            if drug.quantity<item['quantity']: raise serializers.ValidationError(f'Insufficient stock: {drug.name}.')
        prescription=Prescription.objects.create(**data)
        for item in items:
            drug=drugs[item['drug'].pk]
            # Conditional update also protects stock on databases without row locks.
            from django.db.models import F
            changed=Drug.objects.filter(pk=drug.pk,quantity__gte=item['quantity']).update(quantity=F('quantity')-item['quantity'])
            if not changed: raise serializers.ValidationError('Stock changed; please retry.')
            PrescriptionItem.objects.create(prescription=prescription,**item)
            StockLog.objects.create(drug=drug,change=-item['quantity'],reason='Prescription dispensed',prescription=prescription,actor=data['created_by'])
        return prescription

class PaymentSerializer(serializers.ModelSerializer):
    patient_name=serializers.CharField(source='patient.name',read_only=True)
    class Meta:
        model=Payment; fields='__all__'; read_only_fields=['created_by','created_at']

class CommentSerializer(serializers.ModelSerializer):
    author_name=serializers.CharField(source='author.first_name',read_only=True)
    class Meta:
        model=Comment; fields=['id','author_name','body','created_at']

class PostSerializer(serializers.ModelSerializer):
    author_name=serializers.CharField(source='author.first_name',read_only=True)
    comments=CommentSerializer(many=True,read_only=True)
    like_count=serializers.IntegerField(source='likes.count',read_only=True)
    liked=serializers.SerializerMethodField()
    def get_liked(self,obj): return obj.likes.filter(pk=self.context['request'].user.pk).exists()
    class Meta:
        model=Post; fields=['id','body','author_name','created_at','comments','like_count','liked']

class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model=Service; fields='__all__'

class StockLogSerializer(serializers.ModelSerializer):
    drug_name=serializers.CharField(source='drug.name',read_only=True)
    class Meta:
        model=StockLog; fields='__all__'
