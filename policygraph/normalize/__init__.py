from policygraph import CONFIG, NORMALIZED
from policygraph.fetch import MANIFEST
from policygraph.normalize import acs, cdi_fair_plan, cdi_nonrenewal, documents, fhsz, zcta
from policygraph.util import load_yaml

NORMALIZERS = {m.__name__.rsplit(".", 1)[-1]: m for m in (zcta, fhsz, acs, cdi_nonrenewal, cdi_fair_plan, documents)}


def run() -> None:
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    cfg = load_yaml(CONFIG / "sources.yaml")["sources"]
    manifest = load_yaml(MANIFEST)
    for norm in NORMALIZERS.values():  # order matters: zcta before fhsz
        for name, spec in cfg.items():
            if spec["normalizer"] == norm.__name__.rsplit(".", 1)[-1] and name in manifest:
                norm.run(spec, manifest[name])
