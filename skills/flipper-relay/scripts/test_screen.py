"""Offline regression checks. No physical device or external model is contacted."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.dont_write_bytecode = True
spec=importlib.util.spec_from_file_location('screen',Path(__file__).with_name('screen.py'))
screen=importlib.util.module_from_spec(spec);spec.loader.exec_module(screen)
from PIL import Image,ImageDraw,ImageFont


def menu():
    image=Image.new('L',(128,64),255)
    draw=ImageDraw.Draw(image)
    draw.text((5,4),'Settings',fill=0)
    draw.rectangle((2,22,125,33),fill=0)
    draw.text((5,23),'Infrared',fill=255)
    return image


class FakeRelay:
    def __init__(self):
        self.image=menu();self.commands=[];self.transport='BLE';self.fail=False;self.fail_after=False
    def status(self): return {'connected':True,'transport':self.transport}
    def screen(self):
        if self.fail_after and self.commands: raise RuntimeError('capture failed')
        return self.image.copy()
    def button(self,key,long_press):
        self.commands.append((key,long_press))
        if self.fail: raise RuntimeError('timeout')
        self.image.putpixel((127,63),0)
        return {'ok':True}


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.cache=Path(self.tmp.name);self.relay=FakeRelay()
        self.ocr=patch.object(screen,'ocr_lines',return_value={'available':True,'lines':[]});self.ocr.start()
    def tearDown(self): self.ocr.stop();self.tmp.cleanup()
    def observe(self): return screen.observe(self.relay,self.cache)
    def test_single_use_success(self):
        before=self.observe();after=screen.step(self.relay,self.cache,before['observation_id'],'DOWN',settle=0)
        self.assertEqual(after['action'],'rpc_acknowledged');self.assertTrue(after['observation']['screen_changed'])
        with self.assertRaises(ValueError): screen.step(self.relay,self.cache,before['observation_id'],'DOWN')
        self.assertEqual(len(self.relay.commands),1)
    def test_newer_observation_invalidates_old(self):
        older=self.observe();self.observe()
        with self.assertRaises(ValueError):screen.step(self.relay,self.cache,older['observation_id'],'OK')
        self.assertFalse(self.relay.commands)
    def test_age_rechecked_after_preflight(self):
        before=self.observe();start=before['captured_at_unix']
        with patch.object(screen.time,'time',side_effect=[start+59,start+63]):
            with self.assertRaises(ValueError):screen.step(self.relay,self.cache,before['observation_id'],'OK')
        self.assertFalse(self.relay.commands)
    def test_ack_cache_failure_is_explicit(self):
        before=self.observe();real_save=screen.save_json
        def write(path,value):
            if value.get('action_state')=='rpc_acknowledged':raise OSError('disk full')
            real_save(path,value)
        with patch.object(screen,'save_json',side_effect=write):
            result=screen.step(self.relay,self.cache,before['observation_id'],'OK',settle=0)
        self.assertEqual(result['action'],'rpc_acknowledged');self.assertTrue(result['verification'].startswith('failed'))
        self.assertEqual(len(self.relay.commands),1)
    def test_stale_refuses(self):
        before=self.observe();path=self.cache/(before['observation_id']+'.json');before['captured_at_unix']-=61;screen.save_json(path,before)
        with self.assertRaises(ValueError): screen.step(self.relay,self.cache,before['observation_id'],'OK')
        self.assertFalse(self.relay.commands)
    def test_changed_screen_refuses_and_refreshes(self):
        before=self.observe();self.relay.image.putpixel((127,63),0)
        result=screen.step(self.relay,self.cache,before['observation_id'],'OK')
        self.assertEqual(result['action'],'not_sent');self.assertFalse(self.relay.commands)
        self.assertNotEqual(before['observation_id'],result['observation']['observation_id'])
    def test_changed_transport_refuses(self):
        before=self.observe();self.relay.transport='USB'
        self.assertEqual(screen.step(self.relay,self.cache,before['observation_id'],'OK')['action'],'not_sent')
        self.assertFalse(self.relay.commands)
    def test_timeout_never_replays(self):
        before=self.observe();self.relay.fail=True
        self.assertEqual(screen.step(self.relay,self.cache,before['observation_id'],'OK')['action'],'outcome_unknown')
        with self.assertRaises(ValueError):screen.step(self.relay,self.cache,before['observation_id'],'OK')
        self.assertEqual(len(self.relay.commands),1)
    def test_failed_post_capture_keeps_ack(self):
        before=self.observe();self.relay.fail_after=True
        result=screen.step(self.relay,self.cache,before['observation_id'],'DOWN',settle=0)
        self.assertEqual(result['action'],'rpc_acknowledged');self.assertTrue(result['verification'].startswith('failed'))
        self.assertEqual(len(self.relay.commands),1)
    def test_bad_vision_is_unknown(self):
        with patch.object(screen,'vision',side_effect=ValueError('secret must not appear')):
            result=screen.observe(self.relay,self.cache,True)
        self.assertEqual(result['vision']['confidence'],0);self.assertIsNone(result['selected_text'])
        self.assertNotIn('secret',json.dumps(result))
    def test_missing_confidence_is_zero(self):
        result=screen.validate_vision({'screen_type':'menu','visible_rows':['Settings'],'selected_text':'Settings'})
        self.assertEqual(result['confidence'],0)
    def test_invalid_vision_rejected(self):
        for value in [{'confidence':True},{'confidence':float('nan')},{'visible_rows':'bad'},{'screen_type':'run shell'}]:
            with self.assertRaises(ValueError):screen.validate_vision(value)
    def test_image_validation_and_pixel_hash(self):
        image=menu();decoded=screen.decode_image(screen.png_bytes(image))
        self.assertEqual(screen.frame_hash(decoded),screen.frame_hash(image))
        with self.assertRaises(ValueError):screen.decode_image(screen.png_bytes(Image.new('L',(100,100))))
        self.assertTrue(screen.highlight_bands(image))
    def test_no_ocr_explicit(self):
        self.ocr.stop()
        with patch.object(screen.shutil,'which',return_value=None):
            self.assertFalse(screen.ocr_lines(menu())['available'])
    def test_invalid_observation_id(self):
        with self.assertRaises(ValueError):screen.step(self.relay,self.cache,'../config','OK')
    def test_installer_preserves_old_copy(self):
        target=self.cache/'omp/skills/flipper-relay';target.mkdir(parents=True);(target/'old.txt').write_text('old')
        proc=subprocess.run([sys.executable,str(Path(__file__).with_name('install_omp.py')),'--destination',str(target)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr);result=json.loads(proc.stdout)
        self.assertEqual((Path(result['backup'])/'old.txt').read_text(),'old')
        self.assertTrue((target/'scripts/screen.py').is_file());self.assertFalse((target/'old.txt').exists())


class HttpTests(unittest.TestCase):
    def test_real_http_contract_and_no_redirect_or_retry(self):
        calls=[];state={'redirect':False,'failure':False}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                calls.append((self.path,self.headers.get('Authorization'),None))
                if state['redirect']:
                    self.send_response(302);self.send_header('Location','/elsewhere');self.end_headers();return
                self.send_response(503 if state['failure'] else 200);self.end_headers()
                self.wfile.write(screen.png_bytes(menu()) if self.path=='/screen.png' else b'{"connected":true,"transport":"BLE"}')
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append((self.path,self.headers.get('Authorization'),body))
                self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                config=Path(d)/'config.json';config.write_text(json.dumps({'host':'127.0.0.1','port':server.server_port,'agent_token':'fixture-token'}))
                relay=screen.Relay(config);self.assertTrue(relay.status()['connected']);self.assertEqual(relay.screen().size,(128,64))
                self.assertTrue(relay.button('DOWN',False)['ok'])
                self.assertEqual(calls[-1][2],{'operation':'button','key':'DOWN','long_press':False})
                self.assertTrue(all(c[1]=='Bearer fixture-token' for c in calls))
                state['redirect']=True
                with self.assertRaises(RuntimeError):relay.status()
                self.assertEqual(len(calls),4)
                state.update(redirect=False,failure=True)
                with self.assertRaises(RuntimeError):relay.status()
                self.assertEqual(len(calls),5)
        finally:server.shutdown();server.server_close();thread.join()
    def test_vision_request_contains_only_image_and_vision_key(self):
        seen={}
        def fake_request(url,token=None,payload=None,timeout=35):
            seen.update(url=url,token=token,payload=payload)
            return json.dumps({'choices':[{'message':{'content':json.dumps({'screen_type':'menu','visible_rows':['Settings'],'selected_text':'Settings','confidence':.9})}}]}).encode()
        with patch.dict(os.environ,{'FLIPPER_VISION_BASE_URL':'http://127.0.0.1:1234/v1','FLIPPER_VISION_MODEL':'fixture-vision','FLIPPER_VISION_API_KEY':'vision-fixture'}):
            with patch.object(screen,'request',side_effect=fake_request):result=screen.vision(menu())
        self.assertEqual(seen['url'],'http://127.0.0.1:1234/v1/chat/completions')
        self.assertEqual(seen['token'],'vision-fixture');self.assertEqual(result['selected_text'],'Settings')
        self.assertNotIn('tools',seen['payload']);self.assertEqual(seen['payload']['model'],'fixture-vision')
    def test_real_tesseract_fixture(self):
        if not screen.shutil.which('tesseract'):self.skipTest('tesseract unavailable')
        result=screen.ocr_lines(menu())
        self.assertTrue(result['available']);self.assertEqual(result['failed_passes'],[])
        self.assertTrue(result['lines'])


if __name__=='__main__':unittest.main(verbosity=2)
