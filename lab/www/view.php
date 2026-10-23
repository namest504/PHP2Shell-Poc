<?php
$file = $_GET['file'] ?? '';
if ($file !== '') {
    include($file);
}
