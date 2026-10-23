<?php
if (session_start() === false) {
    http_response_code(500);
    echo "session_start failed\n";
    exit;
}
