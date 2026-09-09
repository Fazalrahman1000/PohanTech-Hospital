from django.contrib import admin
from django.urls import path,include
from rest_framework.routers import DefaultRouter
from clinic import views
from clinic.agent import views as ai
router=DefaultRouter()
for name,view in [('doctors',views.Doctors),('patients',views.Patients),('services',views.Services),('drugs',views.Drugs),('prescriptions',views.Prescriptions),('payments',views.Payments),('posts',views.Posts),('stock-logs',views.StockLogs)]: router.register(name,view)
urlpatterns=[path('admin/',admin.site.urls),path('api/auth/<str:action>/',views.Auth.as_view()),path('api/dashboard/',views.Dashboard.as_view()),path('api/accounts/',views.Accounts.as_view()),path('api/reports/',views.Report.as_view()),path('api/',include(router.urls))]
urlpatterns += [path('api/ai/status/',ai.Status.as_view()),path('api/ai/chat/',ai.Chat.as_view()),
    path('api/ai/conversations/clear/',ai.ClearConversation.as_view()),
    path('api/ai/conversations/<int:pk>/clear/',ai.ClearConversation.as_view()),path('api/ai/drafts/',ai.Drafts.as_view()),
    path('api/ai/drafts/<int:pk>/review/',ai.Review.as_view()),path('api/ai/audit/',ai.Audit.as_view()),
    path('api/ai/prescriptions/<int:pk>/pdf/',ai.PrescriptionCopy.as_view())]
