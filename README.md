# MemcLoad


## Description
Homework 9.0 from OTUS.

**TASK:** implement competitive uploading of data in memcache.
Run options:
- `-t`, `--test`, default=False
- `-l`, `--log`, default=None
- `--dry`, default=False
- `--pattern`, default="MemcLoad/*.tsv.gz"
- `--idfa`, default="127.0.0.1:33013"
- `--gaid`, default="127.0.0.1:33014"
- `--adid`, default="127.0.0.1:33015"
- `--dvid`, default="127.0.0.1:33016"

### Run
- Install all required dependencies
```commandline
pip install -r requirements.txt
```
- Run app
```commandline
python3 memc_load.py
```

### Run tests
```commandline
python3 -m unittest test.py -v
```