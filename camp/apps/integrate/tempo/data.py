import pyrsig
import tempfile
import zipfile
import io
def tempo_data():
    token = '' #PUT API ENV TOKEN HERE
    token_dict = {"api_key":token}
    
    with tempfile.TemporaryDirectory() as temp_dir:
        rsigapi = pyrsig.RsigApi(workdir=temp_dir, tempo_kw=token_dict)

        #NOW NEED TO GET API KEY
        #ERROR ValueError: You must set the tempo_kw api_key
        # ds = rsigapi.to_dataframe(
        #     'tempo.l2.no2',
        #     bdate='20250610', 
        #  )
        tempokey = 'tempo.l2.no2.vertical_column_troposphere'
        tempocol = 'no2_vertical_column_troposphere'
        tempodf = rsigapi.to_dataframe(
            tempokey, unit_keys=False, parse_dates=True, backend='xdr'
        )
        print(tempodf)
