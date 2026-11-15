"""Εβδομαδιαία ενημέρωση: παίρνει τα αρχεία (από τον φάκελο incoming/ ή από το minagric),
φτιάχνει ppp-db.json / ppp-meta.json και τα γράφει στη ρίζα μόνο αν άλλαξε κάτι."""
import glob, json, os, subprocess, sys, datetime, shutil, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "work")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def from_incoming():
    inc = os.path.join(ROOT, "incoming")
    mdbs = glob.glob(os.path.join(inc, "*.mdb"))
    for z in glob.glob(os.path.join(inc, "*.zip")):
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                if n.lower().endswith(".mdb"):
                    os.makedirs(WORK, exist_ok=True)
                    p = os.path.join(WORK, "incoming.mdb"); open(p, "wb").write(zf.read(n)); mdbs.append(p)
    lists = [p for p in glob.glob(os.path.join(inc, "*")) if "TKINISI" in os.path.basename(p).upper()
             and "BIOCIDES" not in os.path.basename(p).upper() and p.lower().endswith((".xls", ".xlsx"))]
    if not mdbs:
        return None
    print("Χρήση αρχείων από τον φάκελο incoming/")
    return mdbs[0], (lists[0] if lists else ""), ""

def cleanup_incoming():
    for p in glob.glob(os.path.join(ROOT, "incoming", "*")):
        if os.path.basename(p) != "ΔΙΑΒΑΣΕ-ΜΕ.md": os.remove(p)

def main():
    try:
        run()
    finally:
        cleanup_incoming()

def run():
    os.makedirs(WORK, exist_ok=True)
    src = from_incoming()
    if not src:
        import fetch
        src = fetch.main(WORK)
    mdb, lst, site_date = src
    out = os.path.join(WORK, "out"); os.makedirs(out, exist_ok=True)
    subprocess.check_call([sys.executable, os.path.join(HERE, "build.py"), mdb, lst, out, site_date])

    new = json.load(open(os.path.join(out, "ppp-db.json"), encoding="utf-8"))
    old_p = os.path.join(ROOT, "ppp-db.json")
    old = json.load(open(old_p, encoding="utf-8")) if os.path.exists(old_p) else None

    if len(new["products"]) < 500:
        raise SystemExit("Πολύ λίγα σκευάσματα (%d): κάτι πήγε στραβά, δεν ενημερώνω." % len(new["products"]))
    if old and not new["news"] and old.get("news"):
        new["news"] = old["news"]          # δεν κατέβηκε ο κατάλογος: κρατάμε τα προηγούμενα νέα
    if old:
        a = dict(new); b = dict(old); a.pop("updated", None); b.pop("updated", None)
        if a == b:
            print("Καμία αλλαγή από την προηγούμενη ενημέρωση (%s)." % old["updated"]); return
        if new["updated"] <= old["updated"]:
            new["updated"] = datetime.date.today().isoformat()   # νέο περιεχόμενο: νεότερη ημερομηνία για να το πάρουν τα κινητά

    s = json.dumps(new, ensure_ascii=False, separators=(",", ":"))
    open(os.path.join(ROOT, "ppp-db.json"), "w", encoding="utf-8").write(s)
    meta = {"updated": new["updated"], "products": len(new["products"]), "news": len(new["news"]), "bytes": len(s.encode())}
    open(os.path.join(ROOT, "ppp-meta.json"), "w", encoding="utf-8").write(json.dumps(meta, ensure_ascii=False))
    print("Ενημερώθηκε:", meta)

if __name__ == "__main__":
    main()
