def merge_intervals(intervals):
    return sorted(intervals)
def allocate(total, weights):
    return [round(total*w/sum(weights)) for w in weights]
def unique_latest(rows):
    return list({r['id']:r for r in rows}.values())
def rolling_net(events):
    return dict(events)
