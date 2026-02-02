#!/usr/bin/env bash
set -e

help_text="
Script to run rust driver matrix from within docker

    Optional values can be set via environment variables
    RUST_MATRIX_DIR, TOOLS_JAVA_DIR, JMX_DIR, CCM_DIR, SCYLLA_DBUILD_SO_DIR, RUST_DRIVER_DIR, INSTALL_DIRECTORY

    ./run_test.sh python3 main.py ../scylla-rust-driver ../scylla
"

here="$(realpath $(dirname "$0"))"
DOCKER_IMAGE="$(<"$here/image")"

export RUST_MATRIX_DIR=${RUST_MATRIX_DIR:-`pwd`}
export RUST_DRIVER_DIR=${RUST_DRIVER_DIR:-`pwd`/../scylla-rust-driver}
export CCM_DIR=${CCM_DIR:-`pwd`/../scylla-ccm}

if [[ ! -d ${RUST_MATRIX_DIR} ]]; then
    echo -e "\e[31m\$RUST_MATRIX_DIR = $RUST_MATRIX_DIR doesn't exist\e[0m"
    echo "${help_text}"
    exit 1
fi
if [[ ! -d ${CCM_DIR} ]]; then
    echo -e "\e[31m\$CCM_DIR = $CCM_DIR doesn't exist\e[0m"
    echo "${help_text}"
    exit 1
fi

mkdir -p ${HOME}/.ccm
mkdir -p ${HOME}/.local/lib
mkdir -p ${HOME}/.docker

# export all BUILD_* env vars into the docker run
BUILD_OPTIONS=$(env | sed -n 's/^\(BUILD_[^=]\+\)=.*/--env \1/p')
# export all JOB_* env vars into the docker run
JOB_OPTIONS=$(env | sed -n 's/^\(JOB_[^=]\+\)=.*/--env \1/p')
# export all AWS_* env vars into the docker run
AWS_OPTIONS=$(env | sed -n 's/^\(AWS_[^=]\+\)=.*/--env \1/p')

# if in jenkins also mount the workspace into docker
if [[ -d ${WORKSPACE} ]]; then
WORKSPACE_MNT="-v ${WORKSPACE}:${WORKSPACE}"
else
WORKSPACE_MNT=""
fi

# export all SCYLLA_* env vars into the docker run
SCYLLA_OPTIONS=$(env | sed -n 's/^\(SCYLLA_[^=]\+\)=.*/--env \1/p')

group_args=()
for gid in $(id -G); do
    group_args+=(--group-add "$gid")
done

TMPFS_OPTS="uid=$(id -u),gid=$(id -g),mode=700"

docker_cmd="docker run --detach=true --init \
    ${WORKSPACE_MNT} \
    -v ${RUST_MATRIX_DIR}:${RUST_MATRIX_DIR} \
    -v ${RUST_DRIVER_DIR}:${RUST_DRIVER_DIR} \
    -v ${CCM_DIR}:${CCM_DIR} \
    -e HOME \
    -e SCYLLA_EXT_OPTS \
    -e LC_ALL=en_US.UTF-8 \
    -e DEV_MODE \
    -e WORKSPACE \
    -e CCM_DIR \
    -e CARGO_TERM_COLOR=always \
    ${SCYLLA_OPTIONS} \
    ${BUILD_OPTIONS} \
    ${JOB_OPTIONS} \
    ${AWS_OPTIONS} \
    -w ${RUST_MATRIX_DIR} \
    -v /sys/fs/cgroup:/sys/fs/cgroup:ro \
    -v /etc/passwd:/etc/passwd:ro \
    -v /etc/group:/etc/group:ro \
    -u $(id -u ${USER}):$(id -g ${USER}) \
    ${group_args[@]} \
    --tmpfs ${HOME}:$TMPFS_OPTS,exec \
    -v ${HOME}/.ccm:${HOME}/.ccm \
    --network=host \
    ${DOCKER_IMAGE} bash -c '$*'"

echo "Running Docker: $docker_cmd"
container=$(eval $docker_cmd)


kill_it() {
    if [[ -n "$container" ]]; then
        docker rm -f "$container" > /dev/null
        container=
    fi
}

trap kill_it SIGTERM SIGINT SIGHUP EXIT

docker logs "$container" -f

if [[ -n "$container" ]]; then
    exitcode="$(docker wait "$container")"
else
    exitcode=99
fi

echo "Docker exitcode: $exitcode"

kill_it

trap - SIGTERM SIGINT SIGHUP EXIT

# after "docker kill", docker wait will not print anything
[[ -z "$exitcode" ]] && exitcode=1

exit "$exitcode"
