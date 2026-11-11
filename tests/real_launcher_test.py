"""Exercise launcher ordering with fake Pi processes; no GPIO or network."""
from pathlib import Path
import os
import select
import signal
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RealLauncherTest(unittest.TestCase):
    def test_existing_all_zone_led_process_blocks_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'hardware').mkdir()
            (root / 'static/data').mkdir(parents=True)
            (root / '.venv/bin').mkdir(parents=True)
            (root / 'bin').mkdir()
            script = root / 'hardware/start_real_monitor.sh'
            script.write_text((ROOT / 'hardware/start_real_monitor.sh').read_text())
            for name in ('config.py', 'real_pi_service.py', 'real_flame_reader.py',
                         'real_sensor_outbox.py', 'real_device_runtime.py', 'real_clear_worker.py',
                         'real_allzone_reporter.py', 'all_zone_routes.py', 'cloud_telemetry.py',
                         'led_routes.py', 'led_junctions.py', 'led_layout_162.json'):
                (root / 'hardware' / name).touch()
            (root / 'pi_led_usb.py').touch()
            (root / 'static/data/floorplan.json').touch()
            python = root / '.venv/bin/python'
            python.write_text('#!/usr/bin/env bash\nexit 0\n'); python.chmod(0o755)
            fake_ps = root / 'bin/ps'
            fake_ps.write_text("#!/usr/bin/env bash\nprintf '%s\\n' ' 123 /home/pi/.venv/bin/python hardware/led_all_zones_usb.py --port /dev/ttyACM0'\n")
            fake_ps.chmod(0o755)
            env = {**os.environ, 'PATH': f'{root / "bin"}:' + os.environ['PATH']}
            result = subprocess.run(['bash', str(script)], cwd=root, env=env, input='',
                                    text=True, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('기존 센서·LED·클라우드 프로세스', result.stdout)
            self.assertIn('led_all_zones_usb.py', result.stdout)

    def test_runtime_stops_before_local_state_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'hardware').mkdir()
            (root / 'static/data').mkdir(parents=True)
            (root / '.venv/bin').mkdir(parents=True)
            (root / 'bin').mkdir()
            script = root / 'hardware/start_real_monitor.sh'
            script.write_text((ROOT / 'hardware/start_real_monitor.sh').read_text())
            for name in ('config.py', 'real_pi_service.py', 'real_flame_reader.py',
                         'real_sensor_outbox.py', 'real_device_runtime.py', 'real_clear_worker.py',
                         'real_allzone_reporter.py', 'all_zone_routes.py', 'cloud_telemetry.py',
                         'led_routes.py', 'led_junctions.py', 'led_layout_162.json'):
                (root / 'hardware' / name).touch()
            (root / 'pi_led_usb.py').touch()
            (root / 'static/data/floorplan.json').touch()
            fake_python = root / '.venv/bin/python'
            fake_python.write_text('''#!/usr/bin/env bash
if [[ ${1:-} == -c ]]; then exec /usr/bin/python3 "$@"; fi
name=$1
if [[ ${1:-} == -u && ${2:-} == -m ]]; then name=$3; fi
if [[ $name == hardware.real_pi_service ]]; then touch "$TEST_MARKER"; fi
trap 'echo "$name" >> "$TEST_EVENTS"; exit 0' TERM
if [[ $name == hardware.real_device_runtime ]]; then echo '[CLOUD] 전송 성공 sequence=1'; fi
while true; do sleep 0.1; done
''')
            fake_python.chmod(0o755)
            curl = root / 'bin/curl'
            curl.write_text('''#!/usr/bin/env bash
if [[ $* == *127.0.0.1:5001* && ! -f $TEST_MARKER ]]; then exit 7; fi
echo '{"ledSafetyReady": true}'
''')
            curl.chmod(0o755)
            fake_ps = root / 'bin/ps'
            fake_ps.write_text('#!/usr/bin/env bash\nexit 0\n')
            fake_ps.chmod(0o755)
            events = root / 'events'
            env = {**os.environ, 'PATH': f'{root / "bin"}:' + os.environ['PATH'],
                   'TEST_EVENTS': str(events), 'TEST_MARKER': str(root / 'service-ready')}
            process = subprocess.Popen(['bash', str(script)], cwd=root, stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, env=env, start_new_session=True)
            try:
                process.stdin.write('z' * 40 + '\n'); process.stdin.flush()
                deadline = time.monotonic() + 15
                output = ''
                while time.monotonic() < deadline and '클라우드 첫 보고 완료' not in output:
                    ready, _, _ = select.select([process.stdout], [], [], 1)
                    if ready:
                        output += os.read(process.stdout.fileno(), 4096).decode()
                    if process.poll() is not None:
                        break
                self.assertIn('클라우드 첫 보고 완료', output)
                os.kill(process.pid, signal.SIGINT)
                process.communicate(timeout=20)
                stopped = events.read_text().splitlines()
                self.assertIn('hardware.real_device_runtime', stopped)
                self.assertIn('hardware.real_pi_service', stopped)
                self.assertLess(stopped.index('hardware.real_device_runtime'), stopped.index('hardware.real_pi_service'))
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                process.stdin.close()
                process.stdout.close()


if __name__ == '__main__':
    unittest.main()
