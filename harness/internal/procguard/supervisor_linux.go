//go:build linux

package procguard

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"os/signal"
	"runtime"
	"syscall"
	"time"
)

const maxReapPerPass = 64

var supervisorCleanupTimeout = 5 * time.Second
var supervisorKill = syscall.Kill

func supervise(args []string) int {
	runtime.LockOSThread()
	if os.Geteuid() == 0 || len(args) == 0 {
		return 125
	}
	parentGone, closeParent, err := watchParent()
	if err != nil {
		return 125
	}
	defer closeParent()
	const (
		prSetChildSubreaper = 36
		prSetNoNewPrivs     = 38
	)
	if _, _, errno := syscall.Syscall6(syscall.SYS_PRCTL, prSetChildSubreaper, 1, 0, 0, 0, 0); errno != 0 {
		return 125
	}
	if _, _, errno := syscall.Syscall6(syscall.SYS_PRCTL, prSetNoNewPrivs, 1, 0, 0, 0, 0); errno != 0 {
		return 125
	}
	if _, err := ownedChildren(); err != nil {
		return 125
	}
	signals := make(chan os.Signal, 16)
	signal.Notify(signals, syscall.SIGCHLD, syscall.SIGTERM, syscall.SIGINT)
	defer signal.Stop(signals)
	child := exec.Command(args[0], args[1:]...)
	child.Stdin, child.Stdout, child.Stderr = os.Stdin, os.Stdout, os.Stderr
	child.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if child.Start() != nil {
		return 127
	}
	defer child.Process.Release()
	root := child.Process.Pid
	stopping, rootReaped, exitCode := false, false, 125
	var cleanupTimer *time.Timer
	var cleanupDone <-chan time.Time
	killErrorReported := false
	beginCleanup := func(code int) {
		if stopping {
			return
		}
		stopping, exitCode = true, code
		cleanupTimer = time.NewTimer(supervisorCleanupTimeout)
		cleanupDone = cleanupTimer.C
	}
	defer func() {
		if cleanupTimer != nil {
			cleanupTimer.Stop()
		}
	}()

	for {
		// Check cancellation before each bounded reap batch.
		select {
		case sig := <-signals:
			if sig == syscall.SIGTERM || sig == syscall.SIGINT {
				beginCleanup(143)
			}
		default:
		}
		select {
		case <-parentGone:
			parentGone = nil
			beginCleanup(143)
		default:
		}

		for reaped := 0; reaped < maxReapPerPass; reaped++ {
			select {
			case sig := <-signals:
				if sig == syscall.SIGTERM || sig == syscall.SIGINT {
					beginCleanup(143)
				}
			default:
			}
			var status syscall.WaitStatus
			pid, waitErr := syscall.Wait4(-1, &status, syscall.WNOHANG, nil)
			if errors.Is(waitErr, syscall.EINTR) {
				continue
			}
			if errors.Is(waitErr, syscall.ECHILD) {
				return exitCode
			}
			if waitErr != nil {
				fmt.Fprintln(os.Stderr, "procguard: failed to reap child process")
				return 125
			}
			if pid == 0 {
				break
			}
			if pid == root && !rootReaped {
				rootReaped = true
				exitCode = status.ExitStatus()
				if status.Signaled() {
					exitCode = 128 + int(status.Signal())
				}
				beginCleanup(exitCode)
			}
		}

		if stopping {
			children, childErr := ownedChildren()
			if childErr != nil {
				fmt.Fprintln(os.Stderr, "procguard: failed to inspect child processes")
				return 125
			}
			for _, pid := range children {
				if killErr := supervisorKill(pid, syscall.SIGKILL); killErr != nil && !errors.Is(killErr, syscall.ESRCH) && !killErrorReported {
					fmt.Fprintln(os.Stderr, "procguard: cannot terminate child process; cleanup deadline is active")
					killErrorReported = true
				}
			}
		}

		select {
		case sig := <-signals:
			if sig == syscall.SIGTERM || sig == syscall.SIGINT {
				beginCleanup(143)
			}
		case <-parentGone:
			parentGone = nil
			beginCleanup(143)
		case <-cleanupDone:
			fmt.Fprintln(os.Stderr, "procguard: child cleanup exceeded 5 second deadline")
			return 125
		case <-time.After(10 * time.Millisecond):
		}
	}
}
