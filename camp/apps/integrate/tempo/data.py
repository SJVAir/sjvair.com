import pyrsig
import tempfile
import zipfile
import io
def tempo_data():
    token = 'anonymous' #PUT API ENV TOKEN HERE
    token_dict = {"api_key":token}
    bbox = (-74.8, 40.32, -71.43, 41.4)
    bdate = '2025-06-18'
    
    with tempfile.TemporaryDirectory() as temp_dir:
        api = pyrsig.RsigApi(workdir=temp_dir, tempo_kw=token_dict, bdate=bdate, gridfit=True)
        #print(api.descriptions())
        a = api.descriptions()
        # print(a.iloc[0].prefix)
        # for i in range(len(a)):
        #     if 'tempo' in a.iloc[i].prefix:
        #         print(a.iloc[i])
        
        #NOW NEED TO GET API KEY
        #ERROR ValueError: You must set the tempo_kw api_key
        # ds = rsigapi.to_dataframe(
        #     'tempo.l2.no2',
        #     bdate='20250610', 
        #  )
        # tempokey = 'tempo.l2.no2.vertical_column_troposphere'
        tempokey = 'tempo.l3.o3tot.uv_aerosol_index'
        tempodf = api.to_dataframe(
            tempokey, unit_keys=False, parse_dates=True, backend='xdr'
        )
        print(tempodf)
