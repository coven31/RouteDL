import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import probe_nodes as pn
import routedl_cli as c

V = "vless://11111111-1111-1111-1111-111111111111@1.2.3.4:443?security=reality&type=tcp&sni=a.com&pbk=K&sid=1&fp=chrome#x"


class Core(unittest.TestCase):
    def test_parse(self):
        n = pn.parse_vless(V)
        self.assertEqual((n["host"], n["port"]), ("1.2.3.4", 443))
        for bad in ("", "http://x", "vless://@h:1", "vless://u@h"):
            self.assertIsNone(pn.parse_vless(bad))

    def test_config(self):
        cfg = pn.build_config(pn.parse_vless(V), 1234)
        self.assertEqual(cfg["inbounds"][0]["port"], 1234)
        self.assertEqual(cfg["outbounds"][0]["streamSettings"]["security"], "reality")
        self.assertIsNone(pn.build_config(pn.parse_vless(V.replace("type=tcp", "type=kcp")), 1))

    def test_json_guard(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.json")
            c.save_json(p, [1])
            self.assertEqual(c.load_json(p, []), [1])
            self.assertEqual(c.load_json(p, {}), {})
            with open(p, "w") as f:
                f.write("{bad")
            self.assertEqual(c.load_json(p, {}), {})
            self.assertEqual(c.load_json(os.path.join(d, "none"), {}), {})

    def test_err_lines(self):
        t = "ok\nERROR:\nHTTP Error 403\nfine"
        self.assertTrue(c.HTTP_RE.search(c.err_lines(t)))
        self.assertNotIn("fine", c.err_lines(t))


if __name__ == "__main__":
    unittest.main()
