from okf_testlib import run


def test_fanout_resolution(repo):
    assert run(repo, "fanout").stdout.strip() == "okf: fanout 4 (default)"
    assert run(repo, "fanout", env={"OKF_WIKI_FANOUT": "6"}).stdout.strip() == "okf: fanout 6 (env)"
    assert run(repo, "fanout", "--fanout", "8", env={"OKF_WIKI_FANOUT": "6"}).stdout.strip() == "okf: fanout 8 (flag)"
    r = run(repo, "fanout", "--fanout", "17")
    assert r.returncode == 2 and "must be between 1 and 16" in r.stdout
    r = run(repo, "fanout", env={"OKF_WIKI_FANOUT": "lots"})
    assert r.returncode == 2 and "not a whole number" in r.stdout
