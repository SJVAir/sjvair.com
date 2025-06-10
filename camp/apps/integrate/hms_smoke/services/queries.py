from ..models import Smoke
from datetime import timedelta
from django.db.models import Q, Max
from .helpers import *


#Query for smokes that are ongoing, within the most recent query (so outdated/redundant queries dont clog map)
def ongoing(query_time):
    """
    Query for smokes that are ongoing, within the most recent query 
    (so outdated/redundant queries dont clog map)
    
    Args:
        query_time (int): Time inbetween hms smoke data retrieval

    Returns:
        QuerySet: Iterable set of ongoing smokes from the db
    """ 
    cleaned = totalHelper(
        Int=query_time,
    )
    previous_query = currentTime() - timedelta(hours=cleaned["Int"])
    return Smoke.objects.filter(end__gte=currentTime(), start__lte=currentTime(), observation_time__gte=previous_query)


def ongoing_density(query_time, densityArr):
    """
    Returns an iterable list with Two smoke densities

    Args:
        query_time (int): Time inbetween hms smoke data retrieval
        densityArr (List): density of smoke, can either be "Light", "Medium", "Heavy" (any length)

    Returns:
        QuerySet: Iterable set of ongoing smokes from the db with 0-count Densities
    """
    
    #HELPER TO CHECK DENSITY ARR


    cleaned = totalHelper(
        Densities=densityArr,
        Int=query_time,
    )
    previous_query = currentTime() - timedelta(hours=cleaned["Int"])
    # If at least one valid density was provided, build a query
    if len(cleaned["Densities"])>=1:
        density_query = Q()
        for d in cleaned["Densities"]:
            density_query |= Q(density=d)   
        return Smoke.objects.filter(density_query,end__gte=currentTime(), start__lte=currentTime(),  observation_time__gte=previous_query)
    return Smoke.objects.none()



def latest():
    """
    Uses aggregate max function to find the most recent retrieval of data + uses a range of 5
    minutes before to find the entire query (computations will differ each timedate object by seconds).

    Returns:
        queryset: returns all smokes within 5 minutes of the last query
    """
    latest_max = Smoke.objects.aggregate(Max('observation_time'))['observation_time__max']
    if latest_max:
        latest = latest_max - timedelta(seconds=10)
        return Smoke.objects.filter(observation_time__gte=latest, observation_time__lte=latest_max)
    return Smoke.objects.none()



def latest_density(densityArr):
    """
    Uses aggregate max function to find the most recent retrieval of data + uses a range of 5
    minutes before to find the entire query (computations will differ each timedate object by seconds).

    Also selects data with the densities designated by the argument densityArr

    Args:
        densityArr (List): density of smoke, can either be "Light", "Medium", "Heavy" (any length)

    Returns:
        queryset: returns all smokes within 5 minutes of the last query with a density designated by the input
    """
    cleaned = totalHelper(
        Densities=densityArr,
    )
    latest_max = Smoke.objects.aggregate(Max('observation_time'))['observation_time__max']
    if latest_max:
        latest = latest_max - timedelta(seconds=10)
        density_query=Q()
        for d in cleaned["Densities"]:
            density_query |= Q(density=d)
        if len(cleaned["Densities"])>0:
            return Smoke.objects.filter(density_query, observation_time__gte=latest, observation_time__lte=latest_max)
    return Smoke.objects.none()


def timefilter(start, end):
    """
    This function will hold the logic for error checking and query operation for the time filter operation.
    This query will be used to filter between the selected hours for the current day in UTC time.
    EXPECTS UTC QUERY

    Args:
        start (str): Start time query (UTC)
        end (str): End time query (UTC)

    Returns:
        queryset: queryset that is either empty if there is no maximum observable, empty if there are no smokes in recent query within the filter range
                or filled with smokes within the latest observable query that are within the time filter range.
    """
    latest_max = Smoke.objects.aggregate(Max('observation_time'))['observation_time__max']
    if latest_max:
        latest = latest_max - timedelta(seconds=10)
        return Smoke.objects.filter(end__gte=start, start__lte=end, observation_time__gte=latest, observation_time__lte=latest_max)
    return Smoke.objects.none()
