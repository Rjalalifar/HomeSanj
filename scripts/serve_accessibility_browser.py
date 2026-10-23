"""Run the existing isolated browser harness with explicitly enabled local OTP."""
import os
import runpy

os.environ['ACCESSIBILITY_BROWSER_LIVE_OTP'] = 'true'
runpy.run_path('scripts/serve_phase3_browser.py', run_name='__main__')
