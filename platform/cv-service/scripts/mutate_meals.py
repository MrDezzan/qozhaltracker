import os, pathlib, shutil, subprocess, sys
CV="cv-service"; H=f"{CV}/src/cv_service/health.py"
TESTS=["tests/test_health_rules.py","tests/test_health_norms.py","tests/test_health_days.py","tests/test_health_check.py"]
MUTS=[
 ("MIN_MEALS_TO_JUDGE = 2","MIN_MEALS_TO_JUDGE = 0","норма в один подход тоже судится"),
 ("        and meals_norm >= MIN_MEALS_TO_JUDGE\n","",  "порог нормы подходов не проверяется"),
 ("        and today.feeder_visits == 0","        and today.feeder_visits >= 0","ноль подходов ничего не значит"),
 ("        and meals_norm is not None\n","","отсутствие нормы не мешает"),
 ("    if move_low and feed_low and not missed_meals:","    if move_low and feed_low:","двойная тревога о корме"),
 ("        if feed_low and not missed_meals:","        if feed_low:","двойная тревога о корме, порознь"),
 ('    meals_norm = own_baseline(feed_days, "feeder_visits")','    meals_norm = own_baseline(feed_days, "water_visits")',"норма берётся не из того поля"),
 ('        feeder_visits=int(raw.get("feeder_visits") or 0),',"","поле не читается из базы"),
 ('    feeder_visits: int = field(default=0, kw_only=True)','    feeder_visits: int = field(default=0)',"поле снова позиционное"),
 ("        can_feed\n        and meals_norm is not None","        meals_norm is not None","корм судится на мёртвой камере"),
]
orig=open(H,encoding="utf-8").read()
def run():
    for c in pathlib.Path(CV).rglob("__pycache__"): shutil.rmtree(c,ignore_errors=True)
    return subprocess.run([sys.executable,"-B","-m","pytest","-q","-p","no:cacheprovider",*TESTS],cwd=CV,
      capture_output=True,env=dict(os.environ,PYTHONPATH="src:"+os.environ.get("PYTHONPATH",""),
      PYTHONDONTWRITEBYTECODE="1")).returncode==0
if not run(): print("тесты не проходят до мутаций"); sys.exit(2)
surv=[];miss=[]
try:
    for b,a,n in MUTS:
        if b not in orig: miss.append(n); print(f"  ? {n}"); continue
        open(H,"w",encoding="utf-8").write(orig.replace(b,a,1))
        if run(): surv.append(n); print(f"  ВЫЖИЛ  {n}")
        else: print(f"  убит   {n}")
finally: open(H,"w",encoding="utf-8").write(orig)
print(f"мутантов: {len(MUTS)}, выжило: {len(surv)}, не применено: {len(miss)}")
sys.exit(1 if surv or miss else 0)
