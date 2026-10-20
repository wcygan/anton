package storage

import (
	"github.com/seaweedfs/seaweedfs/weed/storage/types"
	"github.com/stretchr/testify/require"
	"os"
	"testing"
)

type independentlyPersistedIndex struct {
	*durableIndex
	writes int
}

func (i *independentlyPersistedIndex) Put(id types.NeedleId, offset types.Offset, size types.Size) error {
	if err := i.durableIndex.Put(id, offset, size); err != nil {
		return err
	}
	i.writes++
	if i.writes == 1 {
		var err error
		i.image, err = os.ReadFile(i.indexFile.Name())
		return err
	}
	return nil
}

func TestQualificationIndependentlyPersistedIndex(t *testing.T) {
	for _, inline := range []bool{false, true} {
		for _, overwrite := range []bool{false, true} {
			for _, once := range []bool{false, true} {
				name := map[bool]string{false: "batch", true: "inline"}[inline] + "/" + map[bool]string{false: "new", true: "overwrite"}[overwrite] + "/" + map[bool]string{false: "persistent", true: "once"}[once]
				t.Run(name, func(t *testing.T) {
					v, d, i := durableVolume(t)
					_, _, _, err := v.writeNeedle2(fixedNeedle(1, "previous-ack"), true, false, true)
					require.NoError(t, err)
					require.NoError(t, d.Sync())
					require.NoError(t, i.Sync())
					v.nm = &independentlyPersistedIndex{durableIndex: i}
					d.fail, d.once = true, once
					id := uint64(2)
					if overwrite {
						id = 1
					}
					_, _, _, err = v.writeNeedle2(fixedNeedle(id, "unacknowledged-overwrite"), true, true, inline)
					require.Error(t, err)
					recovered := crashImage(t, d, i)
					require.False(t, recovered.IsReadOnly(), "recovery must not leave an index past the data file")
					assertDurablePayload(t, recovered, 1, "previous-ack")
					if !overwrite {
						_, err = recovered.readNeedle(fixedNeedle(2, ""), nil, nil)
						require.Error(t, err)
					}
				})
			}
		}
	}
}
