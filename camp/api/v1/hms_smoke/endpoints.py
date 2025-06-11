
# Create your views here.
from resticus import generics
from camp.apps.integrate.hms_smoke.models import Smoke
#rm
# from camp.apps.integrate.hms_smoke.services.helpers import *
# from camp.apps.integrate.hms_smoke.services.queries import *
from .serializers import SmokeSerializer
#rm import os
from .filters import SmokeFilter
from django.utils import timezone
from datetime import timedelta
from django.db.models import Max

class SmokeMixin:
    model = Smoke
    serializer_class = SmokeSerializer

class SmokeList(SmokeMixin, generics.ListEndpoint):
    filter_class = SmokeFilter

class SmokeDetail(SmokeMixin, generics.DetailEndpoint):
    lookup_field = 'id'
    lookup_url_kwarg = 'smoke_id'

class SmokeListOngoing(SmokeMixin, generics.ListEndpoint):
    filter_class = SmokeFilter
    
    def get_queryset(self):
        queryset = super().get_queryset()
        #prev_query = timezone.now() - timedelta(minutes=59, seconds=59)
        curr_time = timezone.now()
        print("CURR: ",curr_time)
        #print("PREV: ",prev_query)
        latest_max = Smoke.objects.aggregate(Max('created'))['created__max']
        
        queryset = queryset.filter(start__lte=curr_time, end__gte=curr_time, created=latest_max)
        return queryset
        

#rm
# env = os.environ.get
# query_hours = int(os.environ.get('query_hours', 3))

# class OngoingSmokeView(generics.ListEndpoint):
#     model = Smoke
#     serializer_class = SmokeSerializer
    
#     def get_queryset(self):
#         queryset = ongoing(query_hours).order_by('-end')
#         return queryset

# class OngoingSmokeDensityView(generics.ListEndpoint):
#     model = Smoke
#     serializer_class = SmokeSerializer
    
#     def get_queryset(self):
#         densities = self.request.GET.getlist('density')
#         queryset = ongoing_density(query_hours, densities).order_by('-end')
#         return queryset
    
    
# class LatestObeservableSmokeView(generics.ListEndpoint):
#     model = Smoke
#     serializer_class = SmokeSerializer
    
#     def get_queryset(self):
#             queryset = latest().order_by('-observation_time')
#             return queryset


# class LatestObeservableSmokeDensityView(generics.ListEndpoint):
#     model = Smoke
#     serializer_class = SmokeSerializer
    
#     def get_queryset(self):
#         densities = self.request.GET.getlist('density')
#         queryset = latest_density(densities).order_by('-observation_time')
#         return queryset
        

# class SelectSmokeView(generics.Endpoint):
#     model = Smoke
#     serializer_class = SmokeSerializer
#     queryset = Smoke.objects.all()

#     def get(self, *args, **kwargs):
#         try:
#             uuid_str = kwargs['pk']
#             SmallUUID(strCheck(uuid_str))
#             smoke = get_object_or_404(Smoke, pk=uuid_str)
#             smoke_serialized = SmokeSerializer(smoke).serialize()
#             return JsonResponse({"data": smoke_serialized})
#         except Exception as e:
#             uuid_str = self.kwargs.get('pk')
#             raise Http404(f"There was a problem retrieving smoke data for id = {uuid_str}")
    
    
# class SmokeByTimestamp(generics.ListEndpoint):
#     model = Smoke
#     serializer_class = SmokeSerializer
#     queryset = Smoke.objects.all()
    
#     def get_queryset(self):
#         queryset = super().get_queryset()
#         return queryset.order_by('-observation_time')
    

# # Will return today's smokes between times indicated by user according to the most recent observation.
# class StartEndFilter(generics.ListEndpoint):
#     model = Smoke 
#     serializer_class = SmokeSerializer
    
#     def get_queryset(self):
#         start = self.request.GET.get('start')
#         end = self.request.GET.get('end')

#         dt = currentTime()
#         year = dt.year
#         day = dt.timetuple().tm_yday
        
#         start = str(year) + str(day) + " " + start
#         end = str(year) + str(day) + " " + end
        
#         cleaned = totalHelper(
#             Start = start,
#             End = end,
#         )
#         queryset = timefilter(cleaned["Start"], cleaned["End"])
#         return queryset.order_by("-end")
        
        
        
    
    