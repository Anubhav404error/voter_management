from django.contrib import admin
from django.utils.html import format_html
from django.urls import path
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.utils.decorators import method_decorator

from . import views
from .models import VoterField, Voter
import json
from django.db import transaction
from django.utils import timezone
from notifications.models import NotificationType, NotificationTemplate, NotificationLog
from django.conf import settings
import re
import logging
from datetime import datetime
from django.contrib.admin.models import LogEntry, ADDITION
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from .models import Voter, VoterField
from .utils import format_phone_number
from .forms import VoterForm
from notifications.utils import NotificationSender


# Configure logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('voter_management.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Define Excel fields
EXCEL_FIELDS = [
    'MLC CONSTITUNCY', 'ASSEMBLY', 'MANDAL', 'TOWN', 'VILLAGE', 'PSNO',
    'LOCATION', 'PS ADDRESS', 'STREET', 'HNO', 'SNO', 'CARD NO',
    'VOTER NAME', 'MOBILE NO', 'AGE', 'GENDER', 'REL NAME', 'RELATION',
    'VOTER STATUS', 'PARTY', 'CASTE', 'CATEGORY', 'VERIFY STATUS'
]

# Define Excel fields with their corresponding model field names
EXCEL_FIELD_MAPPING = {
    'MLC CONSTITUNCY': 'mlc_constituency',
    'ASSEMBLY': 'assembly',
    'MANDAL': 'mandal',
    'TOWN': 'town',
    'VILLAGE': 'village',
    'PSNO': 'psno',
    'LOCATION': 'location',
    'PS ADDRESS': 'ps_address',
    'STREET': 'street',
    'HNO': 'hno',
    'SNO': 'sno',
    'CARD NO': 'card_no',
    'VOTER NAME': 'voter_name',
    'MOBILE NO': 'mobile_no',
    'AGE': 'age',
    'GENDER': 'gender',
    'REL NAME': 'rel_name',
    'RELATION': 'relation',
    'VOTER STATUS': 'voter_status',
    'PARTY': 'party',
    'CASTE': 'caste',
    'CATEGORY': 'category',
    'VERIFY STATUS': 'verify_status'
}

# Define which fields should be required by default
REQUIRED_FIELDS = ['MLC CONSTITUNCY', 'ASSEMBLY', 'MANDAL', 'SNO', 'MOBILE NO']

# Define field types mapping
FIELD_TYPES = {
    'AGE': 'number',
    'MOBILE NO': 'phone',
    'SNO': 'number',
    'CARD NO': 'number',
    'GENDER': 'select',
}


@admin.register(VoterField)
class VoterFieldAdmin(admin.ModelAdmin):
    list_display = ('name', 'field_type', 'is_required', 'created_at', 'updated_at')
    list_filter = ('field_type', 'is_required')
    search_fields = ('name',)
    ordering = ('name',)
    change_list_template = 'admin/voters/voterfield/change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('api/field/add/', self.add_voter_field, name='voter-field-add'),
            path('api/field/<int:pk>/delete/', self.delete_voter_field, name='voter-field-delete'),
            path('api/field/<int:pk>/update/', self.update_voter_field, name='voter-field-update'),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        if not VoterField.objects.exists():
            self.create_default_fields()

        voter_fields = VoterField.objects.all()
        current_datetime = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

        extra_context.update({
            'voter_fields': voter_fields,
            'add_url_name': 'admin:voter-field-add',
            'delete_url_name': 'admin:voter-field-delete',
            'update_url_name': 'admin:voter-field-update',
            'excel_fields': EXCEL_FIELDS,
            'current_datetime': current_datetime,
            'current_user': request.user.username,
        })

        return super().changelist_view(request, extra_context)

    @transaction.atomic
    def create_default_fields(self):
        for field_name in EXCEL_FIELDS:
            field_type = FIELD_TYPES.get(field_name, 'text')
            is_required = field_name in REQUIRED_FIELDS

            VoterField.objects.get_or_create(
                name=field_name,
                defaults={
                    'field_type': field_type,
                    'is_required': is_required
                }
            )

    @method_decorator(csrf_protect)
    def add_voter_field(self, request):
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                if VoterField.objects.filter(name=data['name']).exists():
                    return JsonResponse({
                        'success': False,
                        'error': 'A field with this name already exists.'
                    })

                field = VoterField.objects.create(
                    name=data['name'],
                    field_type=data['field_type'],
                    is_required=data.get('is_required', False)
                )

                return JsonResponse({
                    'success': True,
                    'id': field.id,
                    'name': field.name,
                    'field_type': field.get_field_type_display(),
                    'is_required': field.is_required
                })
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
        return JsonResponse({'success': False, 'error': 'Invalid request method'})

    @method_decorator(csrf_protect)
    def delete_voter_field(self, request, pk):
        if request.method == 'DELETE':
            try:
                field = VoterField.objects.get(pk=pk)
                if field.name in EXCEL_FIELDS:
                    return JsonResponse({
                        'success': False,
                        'error': 'Cannot delete default Excel fields'
                    })

                field.delete()
                return JsonResponse({'success': True})
            except VoterField.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Field not found'})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
        return JsonResponse({'success': False, 'error': 'Invalid request method'})

    @method_decorator(csrf_protect)
    def update_voter_field(self, request, pk):
        if request.method == 'PATCH':
            try:
                data = json.loads(request.body)
                field = VoterField.objects.get(pk=pk)

                if 'is_required' in data:
                    field.is_required = data['is_required']
                    field.save()

                return JsonResponse({'success': True})
            except VoterField.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Field not found'})
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)})
        return JsonResponse({'success': False, 'error': 'Invalid request method'})


@admin.register(Voter)
class VoterAdmin(admin.ModelAdmin):
    form = VoterForm
    change_list_template = 'admin/voters/voter/change_list.html'
    list_per_page = 50

    def get_list_display(self, request):
        return list(EXCEL_FIELD_MAPPING.keys())

    def get_queryset(self, request):
        queryset = super().get_queryset(request)

        # Get filter values from request
        mlc_filter = request.GET.get('mlc_constituncy')
        assembly_filter = request.GET.get('assembly')
        mandal_filter = request.GET.get('mandal')
        village_filter = request.GET.get('village')

        # Apply filters using the data field
        if mlc_filter:
            queryset = queryset.filter(data__contains={'MLC CONSTITUNCY': mlc_filter})
        if assembly_filter:
            queryset = queryset.filter(data__contains={'ASSEMBLY': assembly_filter})
        if mandal_filter:
            queryset = queryset.filter(data__contains={'MANDAL': mandal_filter})
        if village_filter:
            queryset = queryset.filter(data__contains={'VILLAGE': village_filter})

        return queryset

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('api/add-voter/', self.add_voter, name='add-voter'),
            path('api/voter/<int:pk>/delete/', self.delete_voter, name='voter-delete'),
            path('api/bulk-delete-voters/', self.bulk_delete_voters, name='bulk-delete-voters'),
            path('api/voter/<int:pk>/edit/', self.edit_voter, name='voter-edit'),
            path('send-notification/', self.send_notification, name='send-notification'),
            path('api/get-assemblies/', self.get_assemblies, name='get-assemblies'),
            path('api/get-mandals/', self.get_mandals, name='get-mandals'),
            path('api/get-villages/', self.get_villages, name='get-villages'),
            # path('api/filter-voters/', self.admin_site.admin_view(views.filter_voters), name='filter-voters'),
        ]
        return custom_urls + urls

    def get_assemblies(self, request):
        mlc = request.GET.get('mlc', '')
        if mlc:
            assemblies = Voter.objects.filter(
                data__contains={'MLC CONSTITUNCY': mlc}
            ).values_list('data__ASSEMBLY', flat=True).distinct()
            return JsonResponse(list(filter(None, assemblies)), safe=False)
        return JsonResponse([], safe=False)

    def get_mandals(self, request):
        assembly = request.GET.get('assembly', '')
        if assembly:
            mandals = Voter.objects.filter(
                data__contains={'ASSEMBLY': assembly}
            ).values_list('data__MANDAL', flat=True).distinct()
            return JsonResponse(list(filter(None, mandals)), safe=False)
        return JsonResponse([], safe=False)

    # def get_villages(self, request):
    #     mandal = request.GET.get('mandal', '')
    #     if mandal:
    #         villages = Voter.objects.filter(
    #             data__contains={'MANDAL': mandal}
    #         ).values_list('data__VILLAGE', flat=True).distinct()
    #         return JsonResponse(list(filter(None, villages)), safe=False)
    #     return JsonResponse([], safe=False)
    def get_villages(self, request):
        mandal = request.GET.get('mandal', '')
        if mandal:
            # Add order_by to ensure consistent ordering and use values_list with distinct
            villages = Voter.objects.filter(
                data__contains={'MANDAL': mandal}
            ).values_list('data__VILLAGE', flat=True).distinct().order_by('data__VILLAGE')
            # Filter out None and empty values before returning
            return JsonResponse(list(filter(lambda x: x and x.strip(), villages)), safe=False)
        return JsonResponse([], safe=False)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}

        # Get filtered queryset
        queryset = self.get_queryset(request)

        def get_unique_values(excel_field):
            return sorted(set(
                voter.data.get(excel_field, '')
                for voter in queryset
                if voter.data.get(excel_field)
            ))

        # Get notification types and templates
        try:
            notification_types = NotificationType.objects.all()
            notification_templates = NotificationTemplate.objects.select_related('notification_type').all()

            # Group templates by type
            templates_by_type = {}
            for template in notification_templates:
                if template.notification_type_id not in templates_by_type:
                    templates_by_type[template.notification_type_id] = []
                templates_by_type[template.notification_type_id].append(template)
        except Exception as e:
            logger.error(f"Error fetching notification data: {str(e)}")
            notification_types = []
            notification_templates = []
            templates_by_type = {}

        # Get unique values for filters
        unique_mlc = get_unique_values('MLC CONSTITUNCY')
        # unique_assembly = get_unique_values('ASSEMBLY')
        # unique_mandal = get_unique_values('MANDAL')
        # unique_village = get_unique_values('VILLAGE')

        # Current filter values
        current_filters = {
            'mlc_constituncy': request.GET.get('mlc_constituncy', ''),
            'assembly': request.GET.get('assembly', ''),
            'mandal': request.GET.get('mandal', ''),
            'village': request.GET.get('village', ''),
        }

        current_datetime = timezone.now().strftime('%Y-%m-%d %H:%M:%S')

        extra_context.update({
            'current_datetime': current_datetime,
            'current_user': request.user.username,
            'excel_fields': list(EXCEL_FIELD_MAPPING.keys()),
            'unique_mlc': unique_mlc,
            # 'unique_assembly': unique_assembly,
            # 'unique_mandal': unique_mandal,
            # 'unique_village': unique_village,
            'current_filters': current_filters,
            'notification_types': notification_types,
            'notification_templates': notification_templates,
            'templates_by_type': templates_by_type,
            'notification_channels': [
                {'id': 'SMS', 'name': 'SMS'},
                {'id': 'WA', 'name': 'WhatsApp'},
                {'id': 'BOTH', 'name': 'Both (SMS & WhatsApp)'}
            ]
        })

        return super().changelist_view(request, extra_context)

    @method_decorator(csrf_protect)
    @method_decorator(staff_member_required)
    def send_notification(self, request):
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                type_id = data.get('type_id')
                template_id = data.get('template_id')
                channel = data.get('channel')
                voter_ids = data.get('voter_ids', [])

                if not all([type_id, template_id, channel, voter_ids]):
                    return JsonResponse({
                        'success': False,
                        'error': 'Missing required parameters'
                    }, status=400)

                # Get voters and template
                voters = Voter.objects.filter(id__in=voter_ids)
                try:
                    template = NotificationTemplate.objects.get(id=template_id)
                    if not template.template_id:
                        return JsonResponse({
                            'success': False,
                            'error': 'Template ID is not configured in the template'
                        }, status=400)
                except NotificationTemplate.DoesNotExist:
                    return JsonResponse({
                        'success': False,
                        'error': 'Template not found'
                    }, status=404)

                # Initialize notification sender
                sender = NotificationSender()

                results = {
                    'success_count': 0,
                    'failure_count': 0,
                    'errors': []
                }

                for voter in voters:
                    try:
                        # Validate mobile number
                        if not voter.mobile_no:
                            raise ValueError(f"Voter {voter.id} has no mobile number")

                        # Create notification log
                        notification_log = NotificationLog.objects.create(
                            recipient=voter.mobile_no,
                            template=template,
                            channel=channel,
                            status=NotificationLog.Status.PENDING
                        )

                        # Send notification
                        success, error = sender.send_notification(notification_log)

                        if success:
                            results['success_count'] += 1
                        else:
                            results['failure_count'] += 1
                            results['errors'].append({
                                'voter_id': voter.id,
                                'mobile': voter.mobile_no,
                                'error': error
                            })
                    except Exception as e:
                        logger.error(f"Error processing voter {voter.id}: {str(e)}")
                        results['failure_count'] += 1
                        results['errors'].append({
                            'voter_id': voter.id,
                            'mobile': getattr(voter, 'mobile_no', 'N/A'),
                            'error': str(e)
                        })

                # Return results
                return JsonResponse({
                    'success': True,
                    'data': {
                        'total_sent': results['success_count'],
                        'total_failed': results['failure_count'],
                        'errors': results['errors'] if results['errors'] else None
                    }
                })

            except Exception as e:
                logger.error(f"Error in send_notification view: {str(e)}")
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=500)

        return JsonResponse({
            'success': False,
            'error': 'Invalid request method'
        }, status=405)

    @method_decorator(csrf_protect)
    @method_decorator(staff_member_required)
    def add_voter(self, request):
        if request.method == 'POST':
            try:
                data = json.loads(request.body)

                # Validate required fields
                missing_fields = [field for field in REQUIRED_FIELDS if not data.get(field)]
                if missing_fields:
                    return JsonResponse({
                        'status': 'error',
                        'message': f'Required fields missing: {", ".join(missing_fields)}'
                    }, status=400)

                # Create voter instance
                voter = Voter.objects.create(
                    mlc_constituency=data.get('MLC CONSTITUNCY', ''),
                    assembly=data.get('ASSEMBLY', ''),
                    mandal=data.get('MANDAL', ''),
                    sno=data.get('SNO', ''),
                    mobile_no=data.get('MOBILE NO', ''),
                    data=data
                )

                return JsonResponse({
                    'status': 'success',
                    'message': 'Voter added successfully',
                    'voter': {
                        'id': voter.id,
                        'mlc_constituency': voter.mlc_constituency,
                        'assembly': voter.assembly,
                        'mandal': voter.mandal,
                        'sno': voter.sno,
                        'mobile_no': voter.mobile_no
                    }
                })

            except Exception as e:
                logger.error(f"Error adding voter: {str(e)}")
                return JsonResponse({
                    'status': 'error',
                    'message': str(e)
                }, status=500)

        return JsonResponse({
            'status': 'error',
            'message': 'Invalid method'
        }, status=405)

    @method_decorator(csrf_protect)
    @method_decorator(staff_member_required)
    def delete_voter(self, request, pk):
        if request.method == 'POST':
            try:
                voter = Voter.objects.get(pk=pk)
                voter.delete()
                return JsonResponse({'success': True})
            except Voter.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Voter not found'
                }, status=404)
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=500)
        return JsonResponse({
            'success': False,
            'error': 'Invalid method'
        }, status=405)

    @method_decorator(csrf_protect)
    @method_decorator(staff_member_required)
    def bulk_delete_voters(self, request):
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                voter_ids = data.get('voter_ids', [])

                if not voter_ids:
                    return JsonResponse({
                        'success': False,
                        'error': 'No voters selected'
                    }, status=400)

                Voter.objects.filter(id__in=voter_ids).delete()
                return JsonResponse({'success': True})
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=500)
        return JsonResponse({
            'success': False,
            'error': 'Invalid method'
        }, status=405)

    @method_decorator(csrf_protect)
    @method_decorator(staff_member_required)
    def edit_voter(self, request, pk):
        if request.method == 'POST':
            try:
                voter = Voter.objects.get(pk=pk)
                data = json.loads(request.body)

                # Update voter fields
                for excel_name, model_field in EXCEL_FIELD_MAPPING.items():
                    if excel_name in data:
                        setattr(voter, model_field, data[excel_name])
                        voter.data[excel_name] = data[excel_name]

                voter.save()
                return JsonResponse({'success': True})
            except Voter.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': 'Voter not found'
                }, status=404)
            except Exception as e:
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=500)
        return JsonResponse({
            'success': False,
            'error': 'Invalid method'
        }, status=405)