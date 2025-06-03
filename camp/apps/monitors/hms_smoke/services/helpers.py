import re
from shapely.geometry.base import BaseGeometry
from datetime import datetime, timedelta
from datetime import timezone


    
def stringCheck(input_str):
    """
    general check to prevent html/empty/null strings or non strings

    Args:
        input_str (str): general string safety

    Raises:
        Exception: null exception
        Exception: nonstring
        Exception: empty string
        Exception: html string (xss)

    Returns:
        _type_: string that has been lowercased and stripped of white space on edges
    """

    if input_str is None:
        raise Exception("String input is null.")
    if not isinstance(input_str, str):
        raise Exception("Input is not a string.")
    input_str = input_str.lower().strip()
    
    if input_str == "":
        raise Exception("Input is empty or made of only spaces.")
    if htmlCheck(input_str):
        raise Exception("HTML found in string.")
    return input_str


def htmlCheck(str):
    """
    will be used to confirm string isn't html template

    Args:
        str (str): general string

    Returns:
        _type_: boolean, True if there is html match, False otherwise
    """
    pattern = r'</?[a-z][\s\S]*?>'
    return re.search(pattern, str, re.IGNORECASE) is not None


def geometryCheck(geo):
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
    if geo is None:
        raise Exception("Geometry input is null.")
    if not isinstance(geo, BaseGeometry):
        raise Exception("Not a Shapely geometry object.")
    if not geo.is_valid:
        raise Exception("Invalid geometry object.")
    if geo.is_empty:
        raise Exception("Geometry object is empty.")



def densityArrayCheck(arr):
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


def densityCheck(str):
    #This will prevent anything but the 3 densities and no densities being sent through
    str = stringCheck(str)
    densities = ["light", "medium", "heavy"]
    if not str in densities:
        raise Exception("This is not a valid density")
    return str



def inputDateCheck(str):
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
    str = stringCheck(str)
    if " " not in str:
        raise Exception("Not valid date input.")
    if len(str)>15:
        raise Exception("Date string is too large.")
    
    date, time = str.split()
    if not is_int(date) or not is_int(time):
        raise Exception("This is not a integer.")
    if len(date) <= 4 or len(date) >=8:
        raise Exception("This is not a valid year and day count.")
    if len(time) != 4:
        raise Exception("This is not a valid hour time combination.")
    
    today = datetime.now(timezone.utc)
    year = int(date[:4])
    day_of_year = int(date[4:]) 
    
    if year>today.year+2 or year<2002:
        raise Exception("This is not a valid year.")
    if day_of_year < 0 or day_of_year> 365:
        raise Exception("This is not a valid date")
    
    hour = int(time[:2])
    minute = int(time[2:]) 
    
    if hour <0 or hour >24:
        raise Exception("This hour is outside of a valid range.")
    if minute < 0 or minute>60:
        raise  Exception("This minute is outside of a valid range.")
    if minute > 0 and hour ==24:
        raise Exception("This is not a valid hour time combination.")
    
    date = datetime(year, 1, 1) + timedelta(days=day_of_year - 1)
    dt = date.replace(hour=hour, minute=minute, tzinfo=timezone.utc)
    
    return(dt)
    


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