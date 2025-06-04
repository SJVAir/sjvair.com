
def is_number(str):
    try:
        float(str)
        return True
    except:
        return False