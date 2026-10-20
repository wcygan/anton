package leveldb

import (
	"context"
	"errors"
	"sync"
	"testing"

	"github.com/seaweedfs/seaweedfs/weed/filer"
	"github.com/seaweedfs/seaweedfs/weed/util"
	"github.com/spf13/viper"
	"github.com/stretchr/testify/require"
	"github.com/syndtr/goleveldb/leveldb"
	"github.com/syndtr/goleveldb/leveldb/storage"
)

type durableFS struct {
	storage.Storage
	mu       sync.Mutex
	images   map[storage.FileDesc][]byte
	volatile map[storage.FileDesc][]byte
	fail     bool
}
type durableWriter struct {
	storage.Writer
	owner *durableFS
	fd    storage.FileDesc
}

func (w *durableWriter) Sync() error {
	w.owner.mu.Lock()
	defer w.owner.mu.Unlock()
	if w.owner.fail {
		return errors.New("injected metadata sync EIO")
	}
	if e := w.Writer.Sync(); e != nil {
		return e
	}
	w.owner.images[w.fd] = append([]byte(nil), w.owner.volatile[w.fd]...)
	return nil
}
func (w *durableWriter) Write(p []byte) (int, error) {
	n, e := w.Writer.Write(p)
	w.owner.mu.Lock()
	w.owner.volatile[w.fd] = append(w.owner.volatile[w.fd], p[:n]...)
	w.owner.mu.Unlock()
	return n, e
}
func (d *durableFS) Create(fd storage.FileDesc) (storage.Writer, error) {
	w, e := d.Storage.Create(fd)
	if e != nil {
		return nil, e
	}
	d.mu.Lock()
	delete(d.images, fd)
	d.volatile[fd] = nil
	d.mu.Unlock()
	return &durableWriter{Writer: w, owner: d, fd: fd}, nil
}
func (d *durableFS) Remove(fd storage.FileDesc) error {
	d.mu.Lock()
	delete(d.images, fd)
	delete(d.volatile, fd)
	d.mu.Unlock()
	return d.Storage.Remove(fd)
}
func (d *durableFS) Rename(a, b storage.FileDesc) error {
	d.mu.Lock()
	d.volatile[b] = d.volatile[a]
	delete(d.volatile, a)
	if x, ok := d.images[a]; ok {
		d.images[b] = x
		delete(d.images, a)
	}
	d.mu.Unlock()
	return d.Storage.Rename(a, b)
}
func (d *durableFS) persistAll(t *testing.T) {
	t.Helper()
	d.mu.Lock()
	defer d.mu.Unlock()
	for fd, data := range d.volatile {
		d.images[fd] = append([]byte(nil), data...)
	}
}
func (d *durableFS) crash(t *testing.T) storage.Storage {
	t.Helper()
	target := storage.NewMemStorage()
	d.mu.Lock()
	defer d.mu.Unlock()
	for fd, data := range d.images {
		w, e := target.Create(fd)
		require.NoError(t, e)
		_, e = w.Write(data)
		require.NoError(t, e)
		require.NoError(t, w.Close())
	}
	meta, e := d.Storage.GetMeta()
	require.NoError(t, e)
	require.NoError(t, target.SetMeta(meta))
	return target
}
func qualificationStore(t *testing.T) (*LevelDB2Store, *durableFS) {
	return qualificationStoreMode(t, true)
}
func qualificationStoreMode(t *testing.T, enabled bool) (*LevelDB2Store, *durableFS) {
	t.Helper()
	fs := &durableFS{Storage: storage.NewMemStorage(), images: map[storage.FileDesc][]byte{}, volatile: map[storage.FileDesc][]byte{}}
	cfg := viper.New()
	cfg.Set("leveldb2.dir", t.TempDir())
	cfg.Set("leveldb2.sync", enabled)
	s := &LevelDB2Store{}
	require.NoError(t, s.Initialize(cfg, "leveldb2."))
	for _, db := range s.dbs {
		require.NoError(t, db.Close())
	}
	db, e := leveldb.Open(fs, nil)
	require.NoError(t, e)
	t.Cleanup(func() { db.Close() })
	s.dbs = []*leveldb.DB{db}
	s.dbCount = 1
	return s, fs
}
func recoveredStore(t *testing.T, fs *durableFS) *LevelDB2Store {
	t.Helper()
	db, e := leveldb.Open(fs.crash(t), nil)
	require.NoError(t, e)
	t.Cleanup(func() { db.Close() })
	return &LevelDB2Store{dbs: []*leveldb.DB{db}, dbCount: 1}
}
func qualificationEntry(name string, mode uint32) *filer.Entry {
	return &filer.Entry{FullPath: util.FullPath(name), Attr: filer.Attr{Uid: mode, Mode: 0600}}
}
func qualificationOperation(t *testing.T, s *LevelDB2Store, op string) error {
	ctx := context.Background()
	switch op {
	case "create":
		return s.InsertEntry(ctx, qualificationEntry("/bucket/new", 123))
	case "update":
		return s.UpdateEntry(ctx, qualificationEntry("/bucket/kept", 456))
	case "delete":
		return s.DeleteEntry(ctx, "/bucket/kept")
	case "deleteChildren":
		return s.DeleteFolderChildren(ctx, "/bucket")
	case "kvPut":
		return s.KvPut(ctx, []byte("bucket-setting"), []byte("new-value"))
	case "kvDelete":
		return s.KvDelete(ctx, []byte("bucket-setting"))
	}
	panic(op)
}
func seedMetadata(t *testing.T, s *LevelDB2Store, fs *durableFS) {
	t.Helper()
	ctx := context.Background()
	require.NoError(t, s.InsertEntry(ctx, qualificationEntry("/bucket/kept", 111)))
	require.NoError(t, s.InsertEntry(ctx, qualificationEntry("/other/control", 222)))
	require.NoError(t, s.KvPut(ctx, []byte("bucket-setting"), []byte("old-value")))
	fs.persistAll(t)
}
func TestQualificationMetadataAcknowledgement(t *testing.T) {
	for _, op := range []string{"create", "update", "delete", "deleteChildren", "kvPut", "kvDelete"} {
		t.Run(op, func(t *testing.T) {
			s, fs := qualificationStore(t)
			seedMetadata(t, s, fs)
			require.NoError(t, qualificationOperation(t, s, op))
			r := recoveredStore(t, fs)
			ctx := context.Background()
			control, e := r.FindEntry(ctx, "/other/control")
			require.NoError(t, e)
			require.Equal(t, uint32(222), control.Attr.Uid)
			switch op {
			case "create":
				v, e := r.FindEntry(ctx, "/bucket/new")
				require.NoError(t, e)
				require.Equal(t, uint32(123), v.Attr.Uid)
			case "update":
				v, e := r.FindEntry(ctx, "/bucket/kept")
				require.NoError(t, e)
				require.Equal(t, uint32(456), v.Attr.Uid)
			case "delete", "deleteChildren":
				_, e := r.FindEntry(ctx, "/bucket/kept")
				require.Error(t, e)
			case "kvPut":
				v, e := r.KvGet(ctx, []byte("bucket-setting"))
				require.NoError(t, e)
				require.Equal(t, "new-value", string(v))
			case "kvDelete":
				_, e := r.KvGet(ctx, []byte("bucket-setting"))
				require.Error(t, e)
			}
		})
	}
}
func TestQualificationMetadataSyncFailure(t *testing.T) {
	for _, op := range []string{"create", "update", "delete", "deleteChildren", "kvPut", "kvDelete"} {
		t.Run(op, func(t *testing.T) {
			s, fs := qualificationStore(t)
			seedMetadata(t, s, fs)
			fs.mu.Lock()
			fs.fail = true
			fs.mu.Unlock()
			require.Error(t, qualificationOperation(t, s, op), "metadata sync failure must reach caller")
			r := recoveredStore(t, fs)
			ctx := context.Background()
			v, e := r.FindEntry(ctx, "/bucket/kept")
			require.NoError(t, e)
			require.Equal(t, uint32(111), v.Attr.Uid)
			value, e := r.KvGet(ctx, []byte("bucket-setting"))
			require.NoError(t, e)
			require.Equal(t, "old-value", string(value))
		})
	}
}

func TestQualificationMetadataDropsUnflushedJournal(t *testing.T) {
	s, fs := qualificationStoreMode(t, false)
	seedMetadata(t, s, fs)
	require.NoError(t, s.UpdateEntry(context.Background(), qualificationEntry("/bucket/kept", 999)))
	r := recoveredStore(t, fs)
	v, e := r.FindEntry(context.Background(), "/bucket/kept")
	require.NoError(t, e)
	require.Equal(t, uint32(111), v.Attr.Uid)
}
