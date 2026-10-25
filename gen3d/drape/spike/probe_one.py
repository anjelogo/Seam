import sys
try:
    import warp as wp
except Exception as e:
    print(f"IMPORT_WARP_FAIL: {type(e).__name__}: {e}"); sys.exit(0)
print(f"warp version: {wp.config.version}")
try:
    import warp.sim
except Exception as e:
    print(f"IMPORT_WARP_SIM_FAIL: {type(e).__name__}: {e}"); sys.exit(0)
need = ["ModelBuilder","XPBDIntegrator","Mesh","collide","Model","render"]
print("warp.sim OK -> " + ", ".join(f"{n}={hasattr(warp.sim,n)}" for n in need))
