"""Κατεβάζει από το 1click.minagric.gr τη βάση φυτοπροστατευτικών (dbSYSPEST.zip)
και τον κατάλογο υπουργικών αποφάσεων μετά την 1/1/2016 (xls).
Η σελίδα είναι εφαρμογή ZK: «πατάμε» τα κουμπιά όπως ο browser και παίρνουμε το αρχείο."""
import json, re, sys, os, zipfile, io, time
import requests

BASE = "https://1click.minagric.gr"
PAGE = BASE + "/oneClickUI/frmFytoPro.zul"
UA = {"User-Agent": "Mozilla/5.0 (psekasmoi-data updater; +https://github.com)"}

def zk_click(s, html, comp_id, sid):
    dt = re.search(r"dt:'([^']+)'", html).group(1)
    m = re.search(r"\['[\w.]+','(\w+)',\{id:'" + re.escape(comp_id) + "'", html)
    if not m:
        raise RuntimeError("Δεν βρέθηκε το κουμπί " + comp_id + " στη σελίδα")
    body = {"dtid": dt, "cmd_0": "onClick", "uuid_0": m.group(1),
            "data_0": json.dumps({"pageX": 300, "pageY": 300, "which": 1, "x": 10, "y": 5})}
    r = s.post(BASE + "/oneClickUI/zkau", data=body, timeout=120,
               headers=dict(UA, **{"ZK-SID": str(sid), "Referer": PAGE,
                                   "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}))
    r.raise_for_status()
    urls = re.findall(r'"(/oneClickUI/[^"]+|https?://[^"]+)"', r.text)
    urls = [u.replace("\\/", "/") for u in urls if not u.endswith((".js", ".css", ".wpd", ".png", ".gif"))]
    if not urls:
        raise RuntimeError("Το κουμπί " + comp_id + " δεν έδωσε αρχείο: " + r.text[:300])
    return [u if u.startswith("http") else BASE + u for u in urls]

def get(s, url):
    r = s.get(url, timeout=600, headers=dict(UA, Referer=PAGE))
    r.raise_for_status()
    return r

def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    s = requests.Session()
    html = get(s, PAGE).text
    m = re.search(r"ανανέωση της βάσης δεδομένων στις\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})", html)
    site_date = "%s-%02d-%02d" % (m.group(3), int(m.group(2)), int(m.group(1))) if m else ""

    # 1) Βάση δεδομένων (zip με .mdb)
    mdb_path = None
    for url in zk_click(s, html, "down2", 1):
        r = get(s, url)
        data = r.content
        if data[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = [n for n in z.namelist() if n.lower().endswith((".mdb", ".accdb"))]
                if names:
                    mdb_path = os.path.join(out_dir, "syspest.mdb")
                    open(mdb_path, "wb").write(z.read(names[0]))
                    break
        elif data[:4] == b"\x00\x01\x00\x00":
            mdb_path = os.path.join(out_dir, "syspest.mdb")
            open(mdb_path, "wb").write(data)
            break
    if not mdb_path:
        raise RuntimeError("Δεν κατέβηκε η βάση .mdb")

    # 2) Κατάλογος αποφάσεων (προαιρετικό: αν αποτύχει, κρατάμε τα προηγούμενα νέα)
    list_path = ""
    try:
        html = get(s, PAGE).text
        for url in zk_click(s, html, "fytoProAfter", 1):
            r = get(s, url)
            data = r.content
            if data[:4] == b"\xd0\xcf\x11\xe0" or data[:2] == b"PK":
                ext = ".xls" if data[:4] == b"\xd0\xcf\x11\xe0" else ".xlsx"
                list_path = os.path.join(out_dir, "LIST-TKINISI-DATE" + ext)
                open(list_path, "wb").write(data)
                break
    except Exception as e:
        print("Προειδοποίηση: δεν κατέβηκε ο κατάλογος αποφάσεων:", e)

    print("mdb:", mdb_path, os.path.getsize(mdb_path), "bytes")
    print("list:", list_path or "(όχι)")
    print("ημερομηνία βάσης στο site:", site_date or "(δεν βρέθηκε)")
    return mdb_path, list_path, site_date

if __name__ == "__main__":
    print(main(sys.argv[1] if len(sys.argv) > 1 else "work"))
