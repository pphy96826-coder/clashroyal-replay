import io
import json
from pathlib import Path
import struct
import sys
import unittest
CORE=Path(__file__).resolve().parents[1]/'project/official-web-replay'
sys.path.insert(0,str(CORE))
from windows_native_host import read_message,LIMIT,extension_origin
from import_replay import normalize_saved_links

class BrowserBridgeTests(unittest.TestCase):
    def test_saved_html_link_normalization_keeps_foreign_hosts_untouched(self):
        value='<a href="https://royaleapi.com/card/tower-princess">A</a><a href="https://royaleapi.com.evil.test/card/x">B</a>'
        result=normalize_saved_links(value)
        self.assertIn('href="/card/tower-princess"',result)
        self.assertIn('https://royaleapi.com.evil.test/card/x',result)

    def test_native_frames_reject_truncation_and_excessive_length(self):
        for value in (b'',struct.pack('<I',LIMIT+1),struct.pack('<I',20)+b'{}'):
            with self.assertRaises(ValueError):read_message(io.BytesIO(value))
        raw=json.dumps(dict(command='status',job_id='x')).encode()
        self.assertEqual(read_message(io.BytesIO(struct.pack('<I',len(raw))+raw))['command'],'status')

    def test_native_origin_is_pinned_to_bundled_extension_key(self):
        self.assertEqual(extension_origin(),'chrome-extension://dbjcdkkejbaccfpnicafnkjaehkjhkjf/')

if __name__=='__main__':unittest.main()
