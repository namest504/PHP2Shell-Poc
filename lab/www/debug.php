<?php
echo "PHP " . PHP_VERSION . " (" . PHP_SAPI . ")\n";
echo "upload_progress.enabled = " . ini_get('session.upload_progress.enabled') . "\n";
echo "upload_progress.cleanup = " . ini_get('session.upload_progress.cleanup') . "\n";
echo "allow_url_include = " . ini_get('allow_url_include') . "\n";
echo "memory_limit = " . ini_get('memory_limit') . "\n";
echo "session.save_path = " . ini_get('session.save_path') . "\n";
