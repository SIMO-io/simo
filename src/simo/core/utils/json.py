
def restore_json(data):
    clean_data = {}
    for key, val in data.items():
        if not isinstance(val, str):
            clean_data[key] = val
            continue
        try:
            clean_data[key] = int(val)
            continue
        except:
            pass
        try:
            clean_data[key] = float(val)
            continue
        except:
            pass
        if val.lower() == 'true':
            clean_data[key] = True
        elif val.lower() == 'false':
            clean_data[key] = False
    return clean_data