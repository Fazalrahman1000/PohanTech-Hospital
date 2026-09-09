from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User
@admin.register(User)
class ClinicUserAdmin(UserAdmin):
    fieldsets=UserAdmin.fieldsets+(("Clinic",{'fields':('role','approved','google_sub')}),)
    list_display=['username','email','role','approved','is_active']
