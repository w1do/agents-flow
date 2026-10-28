package agent

// Legacy PID parser regressions remain test helpers; runner supervision no
// longer depends on process-tree sampling or remembered PIDs.

import (
	"errors"
	"os"
	"strconv"
	"strings"
	"syscall"
)

func parseProcStat(data string) (pid, parent int, start uint64, err error) {
	open, close := strings.IndexByte(data, '('), strings.LastIndexByte(data, ')')
	if open <= 0 || close <= open || close+1 >= len(data) {
		return 0, 0, 0, errors.New("invalid proc stat")
	}
	pid, err = strconv.Atoi(strings.TrimSpace(data[:open]))
	if err != nil || pid <= 0 {
		return 0, 0, 0, errors.New("invalid proc pid")
	}
	fields := strings.Fields(data[close+1:])
	if len(fields) < 20 {
		return 0, 0, 0, errors.New("incomplete proc stat")
	}
	parent, err = strconv.Atoi(fields[1])
	if err != nil || parent < 0 {
		return 0, 0, 0, errors.New("invalid proc parent pid")
	}
	start, err = strconv.ParseUint(fields[19], 10, 64)
	if err != nil {
		return 0, 0, 0, errors.New("invalid proc start time")
	}
	return pid, parent, start, nil
}

func readProcStat(pid int) (parent int, start uint64, err error) {
	data, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	if err != nil {
		return 0, 0, err
	}
	_, parent, start, err = parseProcStat(string(data))
	return parent, start, err
}

func processStartTime(pid int) (uint64, error) {
	_, start, err := readProcStat(pid)
	return start, err
}

func killPIDIfSame(pid int, expected uint64) error {
	actual, err := processStartTime(pid)
	if err != nil {
		return err
	}
	if actual != expected {
		return errors.New("process identity changed")
	}
	err = syscall.Kill(pid, syscall.SIGKILL)
	if errors.Is(err, syscall.ESRCH) {
		return nil
	}
	return err
}
