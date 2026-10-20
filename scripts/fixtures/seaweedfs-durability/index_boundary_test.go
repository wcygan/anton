package storage

import (
	"errors"
	"os"
	"testing"

	"github.com/stretchr/testify/require"
)

type failedIndexPosition struct{ *durableIndex }

func (i *failedIndexPosition) IndexFileSize() uint64 { return 0 }
func (i *failedIndexPosition) rollbackIndexPosition() (int64, error) {
	return 0, errors.New("injected index Stat EIO")
}

func TestQualificationIndexPositionFailure(t *testing.T) {
	for _, inline := range []bool{false, true} {
		t.Run(map[bool]string{false: "batch", true: "inline"}[inline], func(t *testing.T) {
			v, d, i := durableVolume(t)
			_, _, _, err := v.writeNeedle2(fixedNeedle(1, "previous-ack"), true, true, inline)
			require.NoError(t, err)
			dataBefore, indexBefore := append([]byte(nil), d.image...), append([]byte(nil), i.image...)
			v.nm = &failedIndexPosition{durableIndex: i}
			d.fail, d.once = true, true
			_, _, _, err = v.writeNeedle2(fixedNeedle(2, "failed-new-write"), true, true, inline)
			require.Error(t, err)
			assertDurablePayload(t, crashImage(t, d, i), 1, "previous-ack")
			dataAfter, err := os.ReadFile(d.Name())
			require.NoError(t, err)
			indexAfter, err := os.ReadFile(i.indexFile.Name())
			require.NoError(t, err)
			require.Equal(t, dataBefore, dataAfter, "unknown rollback boundary must refuse before appending data")
			require.Equal(t, indexBefore, indexAfter, "unknown rollback boundary must not truncate acknowledged entries")
		})
	}
}

func TestQualificationRealIndexPositionError(t *testing.T) {
	v, d, i := durableVolume(t)
	_, _, _, err := v.writeNeedle2(fixedNeedle(1, "previous-ack"), true, true, true)
	require.NoError(t, err)
	positioner, ok := any(i.NeedleMap).(interface{ rollbackIndexPosition() (int64, error) })
	require.True(t, ok, "mapper must expose a fallible rollback boundary")
	end, err := positioner.rollbackIndexPosition()
	require.NoError(t, err)
	require.Equal(t, int64(len(i.image)), end)
	require.NoError(t, i.indexFile.Close())
	_, err = positioner.rollbackIndexPosition()
	require.Error(t, err, "real Stat errors must propagate")
	_, _, _, err = v.writeNeedle2(fixedNeedle(2, "must-not-append"), true, true, true)
	require.Error(t, err)
	actual, err := os.ReadFile(d.Name())
	require.NoError(t, err)
	require.Equal(t, d.image, actual)
}
