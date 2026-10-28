# 기본 에셋

모루는 이 프로젝트를 위해 QPainter 도형으로 직접 제작한 오리지널 새싹 마스코트입니다. 먼작귀 공식 이미지, 로고, 애니메이션, 공식 대사는 포함하지 않습니다. 외부에서 다운로드한 이미지도 없습니다.

- `default_character/manifest.json`: ID/이름/제작자와 상태별 FPS, loop, 프레임 상대 경로.
- `idle/`: 8개 투명 PNG, 느긋한 숨쉬기와 눈 깜빡임.
- `happy/`: 8개 투명 PNG, 클릭 시 반응 후 idle 복귀.
- `icons/`: 같은 원본에서 만든 PNG와 Windows ICO.
- 재생성: `.venv\Scripts\python.exe tools\generate_assets.py`

PNG는 512×512 RGBA이며 앱 크기에 맞춰 한 번 스케일링하고 캐시합니다. manifest는 현재 번들 에셋용이며 사용자 이미지 폴더를 불러오는 UI는 아직 없습니다. 사용자 파일 가져오기·검사·복사·세트 관리는 PHASE 5에서 추가합니다.
