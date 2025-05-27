from django.shortcuts import render
from django.http import JsonResponse
from .models import Voter, VoterField
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
import json
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.db.models import Q
from .models import Voter
from .serializers import VoterSerializer
from notifications.models import NotificationTemplate, NotificationLog
from django.utils import timezone
import requests
from django.conf import settings
import logging
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.permissions import AllowAny


# Set up logging
logger = logging.getLogger(__name__)


@api_view(['GET'])
def get_filter_options(request):
    try:
        mlc_constituncy = request.GET.get('mlc_constituncy', '')
        assembly = request.GET.get('assembly', '')
        mandal = request.GET.get('mandal', '')

        # Base queryset
        queryset = Voter.objects.all()

        # Apply cascading filters
        if mlc_constituncy:
            queryset = queryset.filter(data__contains={'MLC CONSTITUNCY': mlc_constituncy})
        if assembly:
            queryset = queryset.filter(data__contains={'ASSEMBLY': assembly})
        if mandal:
            queryset = queryset.filter(data__contains={'MANDAL': mandal})

        # Get unique values based on applied filters
        assemblies = list(queryset.values_list('data__ASSEMBLY', flat=True).distinct())
        mandals = list(queryset.values_list('data__MANDAL', flat=True).distinct())
        villages = list(queryset.values_list('data__VILLAGE', flat=True).distinct())  # Changed from LOCATION to VILLAGE

        return Response({
            'success': True,
            'data': {
                'assemblies': assemblies,
                'mandals': mandals,
                'villages': villages,
            }
        })
    except Exception as e:
        return Response({
            'success': False,
            'error': str(e)
        })


@api_view(['GET'])
@permission_classes([AllowAny])
def filter_voters(request):
    try:
        # Log incoming request parameters
        logger.info(f"Filter parameters received: {request.GET}")

        # Get filter parameters with consistent naming
        mlc_constituncy = request.GET.get('mlc_constituncy', '')  # Match the frontend naming
        assembly = request.GET.get('assembly', '')
        mandal = request.GET.get('mandal', '')
        village = request.GET.get('village', '')

        # Log the parameters
        logger.info(f"Filtering with: MLC={mlc_constituncy}, Assembly={assembly}, Mandal={mandal}, Village={village}")

        queryset = Voter.objects.all()

        # Apply filters and log counts at each step
        if mlc_constituncy:
            queryset = queryset.filter(data__contains={'MLC CONSTITUNCY': mlc_constituncy})
            logger.info(f"After MLC filter: {queryset.count()} records")

        if assembly:
            queryset = queryset.filter(data__contains={'ASSEMBLY': assembly})
            logger.info(f"After Assembly filter: {queryset.count()} records")

        if mandal:
            queryset = queryset.filter(data__contains={'MANDAL': mandal})
            logger.info(f"After Mandal filter: {queryset.count()} records")

        if village:
            queryset = queryset.filter(data__contains={'VILLAGE': village})
            logger.info(f"After Village filter: {queryset.count()} records")

        serializer = VoterSerializer(queryset, many=True)

        response_data = {
            'success': True,
            'count': queryset.count(),
            'data': serializer.data
        }

        logger.info(f"Returning {queryset.count()} records")
        return JsonResponse(response_data, safe=False)

    except Exception as e:
        logger.error(f"Error in filter_voters: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e),
            'detail': 'An error occurred while filtering voters'
        }, status=500)

def voter_list(request):
    voters = Voter.objects.all()
    return JsonResponse({
        'count': voters.count(),
        'fields': list(VoterField.objects.values('name', 'field_type'))
    })


@require_POST
@staff_member_required
def send_notification(request):
    try:
        data = json.loads(request.body)
        template_id = data.get('template_id')
        channel = data.get('channel')
        voter_ids = data.get('voter_ids', [])

        if not all([template_id, channel, voter_ids]):
            return JsonResponse({
                'success': False,
                'error': 'Missing required parameters'
            })

        # Forward the request to notifications app
        response = requests.post(
            f"{request.scheme}://{request.get_host()}/notifications/send/",
            json={
                'template_id': template_id,
                'channel': channel,
                'recipients': voter_ids
            }
        )

        return JsonResponse(response.json())
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})