from ..models import Smoke
from datetime import timedelta, timezone
from django.db.models import Q
from .helpers import *
from django.db.models import Max

#Query for smokes that are ongoing, within the most recent query (so outdated/redundant queries dont clog map)
def query_ongoing_smoke(query_time):
    """
    Query for smokes that are ongoing, within the most recent query 
    (so outdated/redundant queries dont clog map)
    
    Args:
        query_time (int): Time inbetween hms smoke data retrieval

    Returns:
        QuerySet: Iterable set of ongoing smokes from the db
    """ 
    if is_int(query_time):
        query_time = int(query_time)
    else:
        raise Exception('Query time is not an integer, fix in environment variable')
    currentTime = datetime.now(timezone.utc) 
    previous_query = currentTime - timedelta(hours=query_time)
    
    return Smoke.objects.filter(end__gte=currentTime, start__lte=currentTime, observation_time__gte=previous_query)


def query_ongoing_density_smoke(query_time, densityArr):
    """
    Returns an iterable list with Two smoke densities

    Args:
        query_time (int): Time inbetween hms smoke data retrieval
        densityArr (List): density of smoke, can either be "Light", "Medium", "Heavy" (any length)

    Returns:
        QuerySet: Iterable set of ongoing smokes from the db with 0-count Densities
    """
    
    #HELPER TO CHECK DENSITY ARR

    densityArr = densityArrayCheck(densityArr)
    if is_int(query_time):
        query_time = int(query_time)
    else:
        raise Exception('Query time is not an integer, fix in environment variable')
    #Previous ongoing smokes
    currentTime = datetime.now(timezone.utc)
    previous_query = currentTime - timedelta(hours=query_time)
    #set an array with the possible densities

    # If at least one valid density was provided, build a query
    if len(densityArr)>=1:
        density_query = Q()
        for d in densityArr:
            density_query |= Q(density=d)   
        return Smoke.objects.filter(density_query,end__gte=currentTime, start__lte=currentTime,  observation_time__gte=previous_query)
    #
    #Else return NO Objects aka search for where Density = "NONE"
    return Smoke.objects.none()



def query_latest_smoke():
    """
    Uses aggregate max function to find the most recent retrieval of data + uses a range of 5
    minutes before to find the entire query (computations will differ each timedate object by seconds).

    Returns:
        queryset: returns all smokes within 5 minutes of the last query
    """
    latest_time = Smoke.objects.aggregate(Max('observation_time'))['observation_time__max']
    if latest_time:
        five_mins_before_latest = latest_time - timedelta(seconds=10)
        return Smoke.objects.filter(observation_time__gte=five_mins_before_latest, observation_time__lte=latest_time)
    return Smoke.objects.none()



def query_latest_smoke_density(densityArr):
    """
    Uses aggregate max function to find the most recent retrieval of data + uses a range of 5
    minutes before to find the entire query (computations will differ each timedate object by seconds).

    Also selects data with the densities designated by the argument densityArr

    Args:
        densityArr (List): density of smoke, can either be "Light", "Medium", "Heavy" (any length)

    Returns:
        queryset: returns all smokes within 5 minutes of the last query with a density designated by the input
    """
    densityArr = densityArrayCheck(densityArr)
    latest_time = Smoke.objects.aggregate(Max('observation_time'))['observation_time__max']
    if latest_time:
        five_mins_before_latest = latest_time - timedelta(seconds=10)
        density_query=Q()
        for d in densityArr:
            density_query |= Q(density=d)
        if len(densityArr)>0:
            return Smoke.objects.filter(density_query, observation_time__gte=five_mins_before_latest, observation_time__lte=latest_time)
    return Smoke.objects.none()