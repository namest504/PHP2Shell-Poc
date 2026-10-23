<?php
if (session_start() === false) {
    http_response_code(500);
    echo "session_start failed\n";
    exit;
}
$key = ini_get('session.upload_progress.prefix') . ($_POST[ini_get('session.upload_progress.name')] ?? '');
if (isset($_SESSION[$key])) {
    echo "progress: " . json_encode($_SESSION[$key]) . "\n";
}
session_write_close();
