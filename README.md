# Backend & CI/CD Guide

## 목차

1. [논의 사항](#논의-사항)
2. [Backend](#backend)
3. [CI/CD](#cicd)
4. [Git](#git)

## 1. 논의 사항

- 폴더 구조는 기능 단위로 분리
- 각 기능 디렉토리에는 반드시 `Dockerfile` 포함
- main 브랜치에 push 시 자동 빌드하여 ECR로 Image Push 진행

## 2. Backend

### 2.1. Backend 담당자가 지켜야할 규칙

백엔드 개발자가 지켜야 할 기본 규칙은 다음과 같습니다.

- 기능 단위로 폴더 구분하여 코드 작성
- 각 폴더별 반드시 `Dockerfile` 포함
- 신규 기능 추가 시
  1. 최상위 디렉토리에 `<feature-name>` 폴더 생성
  2. `Dockerfile` 작성
  3. main 브랜치에 push → CI/CD 파이프라인 실행

## 3. CI/CD

CI/CD 파이프라인은 main 브랜치 push하면 자동으로 실행됩니다.

### 3.1. 개요

#### 3.1.1. Workflow 개요

- GitHub Actions → AWS OIDC Role 인증
- Amazon ECR 로그인 (`aws-actions/amazon-ecr-login@v2`)
- 기능별 Docker Build & Push
- Repository 이름: `backend-service/<feature>`
- Tag:
  - 최신: `v1.0.1`, `latest`
  - 이전: `v1.0.0`

### 3.1.2. 버전 관리 규칙

- **major**: 1 (기본값)
- **minor**: true 선택시 증가 / Actions -> CI on ECR에서 Run workflow 선택 -> 체크박스 Check하여 실행하면 증가
- **patch**: 자동 증가(minor 증가시 0으로 초기화)
- 예시:
  - `v1.0.3 → v1.0.4` (자동 Patch 증가)
  - `minor` 지정 시 → `v1.1.0`

### 3.1.3. 빌드 확인

- `{AWS_ACCOUNT_ID}.dkr.ecr.ap-northeast-2.amazonaws.com/backend-service/<feature>:<Tag>`

## 4. Git 관리

### 4.1. .gitmessage 적용 방법

1. commit.template 실행

```bash
git config commit.template .gitmessage.txt
```

2. core.edit 실헹

```bash
git config core.editor "code --wait"
```

3. 적용 확인 방법

```bash
git config --get commit.template
```

### 4.2. IDE에서 사용 방법

1. IDE에서 Commit 입력(UI 또는 terminal 가능)
2. 커밋 메시지 작성

- COMMIT_EDITMSG 파일 생성되는데 해당 부분 예시에 적힌 부분 (Option) 부분 제외하고 전체 입력
- Commit 취소하고 싶다면, 저장하지말고 바로 닫기

3. COMMIT_EDITMSG 파일 저장하고 닫으면 commit 자동 완료

### 4.3. Git Branch 전략

> Git Flow는 현재 적용하기에 무겁다고 판단되어, 기준 브랜치 `main` 하나이며, 짧은 기능 브랜치에서 작업후 PR(Squash merge)로 `main`에 합칩니다.

- 기준 브랜치 `main` : 항상 배포 가능한 상태
- 작업 브랜치 규칙
  - 예시
    - `<type>/<JIRA-번호>-<기능>`
    - `feat/SCRUM-217-upload-dnd`
    - `fix/SCRUM-245-login-bug`
    - `chore/SCRUM-201-upgrade-deps`
  - `<type> 목록`
    - feat : 새로운 기능 추가
    - fix : 버그 수정
    - docs : 문서 수정
    - test : 테스트 코드 작업
    - refactor : 코드 리팩토링 (기능 동작 변화 없음)
    - style : 코드 의미에 영향을 주지 않는 변경사항
    - chore : 빌드 부분 혹은 패키지 매니저 수정사항, 설정/의존성 등
    - ci : CI/CD 작업
- 권장 사항
  - 브랜치는 **작게/짧게** 운용(7일 이내 Merge)
  - 긴급 이슈는 `fix/SCRUM-xxx-hotfix-...`로 분리하여 바로 PR -> Squash merge
