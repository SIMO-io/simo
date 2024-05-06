
def restore_json(data):
    for key, val in data.items():
        if not isinstance(val, str):
            continue
        try:
            data[key] = int(val)
            continue
        except:
            pass
        try:
            data[key] = float(val)
            continue
        except:
            pass
        if val.lower() == 'true':
            data[key] = True
        elif val.lower() == 'false':
            data[key] = False
    return data