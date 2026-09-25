"""Committed native balance deltas from diffMode B2 observations."""
def _entries(doc):
    if isinstance(doc,list):
        out={}
        for item in doc:
            out.update(item.get('trace',{}))
        return out
    return doc.get('trace',doc) if isinstance(doc,dict) else {}

def committed_native_delta(pre_doc, post_doc):
    # B2 poststates rows carry explicit `prestate` and `poststate` maps.
    pre=_entries(pre_doc); post=_entries(post_doc)
    if isinstance(post_doc,dict) and 'prestate' in post_doc:
        pre=post_doc.get('prestate',{}); post=post_doc.get('poststate',{})
    addresses=set(pre)|set(post); out={}
    for a in addresses:
        try: out[a.lower()]=int(post.get(a,{}).get('balance','0x0'),0)-int(pre.get(a,{}).get('balance','0x0'),0)
        except (TypeError,ValueError): continue
    return {a:v for a,v in out.items() if v}
