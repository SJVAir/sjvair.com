import re
from shapely.geometry.base import BaseGeometry
from django.contrib.gis.geos import GEOSGeometry
from datetime import datetime, timedelta
from datetime import timezone


    
def strCheck(string):
    """
    general check to prevent html/empty/null strings or non strings

    Args:
        string (str): general string safety

    Raises:
        Exception: null exception
        Exception: nonstring
        Exception: empty string
        Exception: html string (xss)

    Returns:
        _type_: string that has been lowercased and stripped of white space on edges
    """

    if not string:
        raise Exception("String input is null.")
    if not isinstance(string, str):
        raise Exception("Input is not a string.")
    string = string.lower().strip()
    
    if string == "":
        raise Exception("Input is empty or made of only spaces.")
    if HTMLCheck(string):
        raise Exception("HTML found in string.")
    return string


def HTMLCheck(string):
    """
    will be used to confirm string isn't html template

    Args:
        string (str): general string

    Returns:
        _type_: boolean, True if there is html match, False otherwise
    """
    pattern = r'</?[a-z][\s\S]*?>'
    return re.search(pattern, string, re.IGNORECASE) is not None


def geoCheck(geo):
    """
    will be used to prevent null/empty/nonvalid geometry objects

    Args:
        geo (shapely): hms smoke data from geoPandas dataframe

    Raises:
        Exception: null
        Exception: not a shapely obj
        Exception: invalid obj
        Exception: empty obj
    """
    if not geo:
        raise Exception("Geometry input is null.")
    if not isinstance(geo, (BaseGeometry, GEOSGeometry)):
        raise Exception("Not a Shapely or GEOS geometry object.")
    if isinstance(geo, BaseGeometry):
        if not geo.is_valid:
            raise Exception("Invalid geometry object.")
        if geo.is_empty:
            raise Exception("Geometry object is empty.")
    return geo


def densitiesCheck(arr):
    """
        Confirm the density array has only light, medium, or heavy can return none for no results
        
    Args:
        arr (List): arr, which is either empty, or has densities

    Raises:
        Exception: null
        Exception: confirm it is a list
        Exception: too many inputs
        Exception: input is not a density

    Returns:
        _type_: array, which is either empty for no selected densities (remove from map), or 
            has a comnbination of the 3 densities
    """
    if arr is None:
        raise Exception("Array is null.")
    if not isinstance(arr, list):
        raise Exception("This is not a list")
    if len(arr) == 0:
        return arr  
    if len(arr) > 3:
        raise Exception("Too many inputs in density array.")
    
    newArr = []
    
    for d in arr:
        d = densityCheck(d)
        if d in newArr:
            continue
        else:
            newArr.append(d)
    return newArr


def densityCheck(string):
    #This will prevent anything but the 3 densities and no densities being sent through
    string = strCheck(string)
    densities = ["light", "medium", "heavy"]
    if string not in densities:
        raise Exception("This is not a valid density")
    return string



def dateCheck(string):
    """
    Convert the start/end string to a datetime object.
    Will be done by splitting yearday from hourminute.
    Then splitting the two, casting as ints, then creating a datetime object

    Args:
        String_Time (Str): This is entered as "YearDayofYear HourMinute" 

    Raises:
        Exception: the string has a space
        Exception: yearday hourmin should be set to a relative length
        Exception: not an int
        Exception: length of year always 4 for now + length of day 1-3
        Exception: hour minute = len of 4
        Exception: data starts in 2002, accounts for smokes that end 2 years past current year
        Exception: accounts if data can go to day 0 or day 365 in a year
        #POSSIBLE ERROR: IF DATE TIME DOESNT ACCEPT 0 or 365
        
        Exception: cannot reach hour 25 or -1
        Exception: 60 mins in hour
        Exception: cannot be 24 hrs and 1 minute
        
    Returns:
        aware_dt: aware date localized to pst time so users (based in ca) can easily understand data
    """
    string = strCheck(string)
    if " " not in string:
        raise Exception("Not valid date input.")
    if len(string)>15:
        raise Exception("Date string is too large.")
    
    date, time = string.split()
    if not is_int(date) or not is_int(time):
        raise Exception("This is not a integer.")
    if len(date) <= 4 or len(date) >= 8:
        raise Exception("This is not a valid year and day count.")
    if len(time) != 4:
        raise Exception("This is not a valid hour time combination.")
    
    today = datetime.now(timezone.utc)
    year = int(date[:4])
    day = int(date[4:]) 
    
    if year > today.year+2 or year < 2002:
        raise Exception("This is not a valid year.")
    if day < 0 or day> 365:
        raise Exception("This is not a valid date")
    
    hour = int(time[:2])
    minute = int(time[2:]) 
    
    if hour < 0 or hour > 24:
        raise Exception("This hour is outside of a valid range.")
    if minute < 0 or minute > 60:
        raise  Exception("This minute is outside of a valid range.")
    if minute > 0 and hour == 24:
        raise Exception("This is not a valid hour time combination.")
    
    date = datetime(year, 1, 1)+timedelta(days=day-1)
    dt = date.replace(hour=hour, minute=minute, tzinfo=timezone.utc)
    
    return(dt)
    
#Helper function to check all smoke entry data properties
def totalHelper(**kwargs):
    result = {}

    if "Density" in kwargs:
        result["Density"] = densityCheck(kwargs["Density"])
        
    if "Densities" in kwargs:
        result["Densities"] = densitiesCheck(kwargs["Densities"])
    
    if "Satellite" in kwargs:
        result["Satellite"] = strCheck(kwargs["Satellite"])
    
    if "FID" in kwargs:
        if is_int(kwargs["FID"]):
            result["FID"] = int(kwargs["FID"])

    if "Start" in kwargs:
        result["Start"] = dateCheck(kwargs["Start"])

    if "End" in kwargs:
        result["End"] = dateCheck(kwargs["End"])
    
    if "Geometry" in kwargs:
        result["Geometry"] = geoCheck(kwargs["Geometry"])

    return result


def is_int(s):
    """
    Checks if the string is an integer

    Args:
        s (str): string that could be only numbers

    Returns:
        _type_: Boolean if integer, then True, if not an int False
    """
    try:
        int(s)
        return True
    except (ValueError, TypeError):
        return False