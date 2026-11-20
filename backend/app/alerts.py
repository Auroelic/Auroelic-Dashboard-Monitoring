METRICS = {"cpu": "CPU", "mem": "Memory", "disk": "Disk"}
HYST = 3  # an alert resolves once the value drops HYST points below the threshold


class AlertEngine:
    """Opens an alert when the level persists for `sustain` consecutive samples."""

    def __init__(self, store, thresholds, sustain=2):
        self.store, self.t, self.sustain = store, thresholds, sustain
        self.open = {a["metric"]: a for a in store.alerts("open", 50)}
        self.cand = {}

    def _level(self, m, v):
        warn, crit = self.t[f"{m}_warn"], self.t[f"{m}_crit"]
        cur = self.open.get(m)
        if v >= crit or (cur and cur["severity"] == "critical" and v >= crit - HYST):
            return "critical"
        if v >= warn or (cur and v >= warn - HYST):
            return "warning"
        return None

    def evaluate(self, ts, values, cause):
        events = []
        for m, v in values.items():
            lvl = self._level(m, v)
            cur = self.open.get(m)
            if lvl == (cur["severity"] if cur else None):
                self.cand.pop(m, None)
                continue
            prev, n = self.cand.get(m, (None, 0))
            n = n + 1 if prev == lvl else 1
            self.cand[m] = (lvl, n)
            if n < self.sustain:
                continue
            self.cand.pop(m)
            if cur:
                self.store.resolve_alert(cur["id"], ts)
                events.append({"event": "resolved", "id": cur["id"], "metric": m})
                del self.open[m]
            if lvl:
                thr = self.t[f"{m}_{'crit' if lvl == 'critical' else 'warn'}"]
                msg = f"{METRICS[m]} usage {v:.1f}% exceeded the {lvl} threshold ({thr:g}%)"
                a = self.store.add_alert(ts, m, lvl, round(v, 1), thr, msg, cause(m))
                self.open[m] = a
                events.append({"event": "opened", **a})
        return events

    def status(self):
        sev = {a["severity"] for a in self.open.values()}
        return "critical" if "critical" in sev else "warning" if sev else "online"
