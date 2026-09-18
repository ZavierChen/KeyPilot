"""Check actual on-disk voice dependencies in the process that will use them."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .install_layout import voice_directory
from .user_settings import assistant_settings_path, save_settings


def check_startup(project_dir: Path) -> dict:
    settings_path = assistant_settings_path(project_dir)
    directory = voice_directory()
    report = dict(pid=os.getpid(), executable=sys.executable, project_dir=str(project_dir),
                  settings_path=str(settings_path), voice_directory=str(directory),
                  voices=[], errors=[])
    try:
        settings = json.loads(settings_path.read_text(encoding='utf-8-sig'))
        if not isinstance(settings, dict):
            raise ValueError('Settings must be an object')
    except FileNotFoundError:
        settings = {}
    except (OSError, ValueError) as exc:
        report['errors'].append(f'设置无法读取：{exc}')
        settings = {}
    selected = str(settings.get('custom_voice_pack_id', ''))
    label = str(settings.get('custom_voice_pack', '关闭'))
    report.update(selected_id=selected, selected_label=label)
    selected_config = None
    try:
        for folder in directory.iterdir():
            if not folder.is_dir():
                continue
            try:
                config = json.loads((folder / 'voice.json').read_text(encoding='utf-8-sig'))
                if not isinstance(config, dict) or not config.get('ready'):
                    continue
                report['voices'].append(dict(id=folder.name, name=config.get('name', folder.name)))
                if folder.name == selected or (not selected and config.get('name') == label):
                    selected_config = config
            except (OSError, ValueError):
                continue
    except OSError as exc:
        if selected or label != '关闭':
            report['errors'].append(f'语音目录无法读取：{exc}')
    if selected or label != '关闭':
        if selected_config is None:
            report['errors'].append(f'已选语音包无法读取：{label}（{selected}）')
        else:
            required = ['python', 'site_packages', 'reference_audio', 'vocoder', 'data_dir',
                        'lexicon', 'index', 'rvc_root', 'ffmpeg', 'api_key_path']
            paths = [selected_config[k] for k in required if selected_config.get(k)]
            if selected_config.get('engine') != 'volcengine':
                paths += [selected_config['model']] if selected_config.get('model') else []
                paths += list(selected_config.get('language_models', {}).values())
            paths += [r['audio'] for r in selected_config.get('language_references', {}).values()]
            for value in dict.fromkeys(paths):
                p = Path(value)
                try:
                    if not p.is_absolute():
                        raise ValueError('路径必须为绝对路径')
                    if p.is_dir():
                        list(p.iterdir())
                        if selected_config.get('engine') == 'zipvoice' and str(p) in (
                                str(selected_config.get('model', '')),
                                *map(str, selected_config.get('language_models', {}).values())):
                            for name in ('encoder.int8.onnx', 'decoder.int8.onnx', 'tokens.txt'):
                                with (p / name).open('rb') as stream:
                                    stream.read(1)
                    else:
                        with p.open('rb') as stream:
                            stream.read(1)
                except (OSError, ValueError) as exc:
                    report['errors'].append(f'{p}: {exc}')
            report['quality_preset'] = selected_config.get('quality_preset')
    report['ok'] = not report['errors']
    try:
        save_settings(settings_path.parent / 'startup-diagnostic.json', report)
    except OSError:
        pass
    return report
