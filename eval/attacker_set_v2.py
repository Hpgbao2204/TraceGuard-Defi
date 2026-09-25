"""Fail-closed attacker subtree derivation."""
def derive(trace, sender):
    att={str(sender).lower()} if sender else set(); created=[]
    changed=True
    while changed:
        changed=False
        for x in trace or []:
            if x.get('event')!='enter' or x.get('type') not in {'CREATE','CREATE2'}: continue
            caller=str(x.get('from','')).lower(); child=str(x.get('to','')).lower()
            if caller in att and child and child not in att:
                att.add(child); created.append(child); changed=True
    return att, created
