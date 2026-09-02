Source: pre-fix moby/libnetwork endpoint_cnt.go, reduced to the relevant storage path.

type endpointCnt struct {
    n        *network
    Count    uint64
    dbIndex  uint64
    dbExists bool
    sync.Mutex
}

const epCntKeyPrefix = "endpoint_count"

func (ec *endpointCnt) Key() []string {
    ec.Lock()
    defer ec.Unlock()
    return []string{epCntKeyPrefix, ec.n.id}
}

func (ec *endpointCnt) Exists() bool {
    ec.Lock()
    defer ec.Unlock()
    return ec.dbExists
}

func (ec *endpointCnt) New() datastore.KVObject {
    ec.Lock()
    defer ec.Unlock()
    return &endpointCnt{n: ec.n}
}

func (ec *endpointCnt) atomicIncDecEpCnt(inc bool) error {
retry:
    ec.Lock()
    if inc {
        ec.Count++
    } else {
        if ec.Count > 0 {
            ec.Count--
        }
    }
    ec.Unlock()

    store := ec.n.getController().getStore(ec.DataScope())
    if store == nil {
        return fmt.Errorf("store not found for scope %s", ec.DataScope())
    }

    if err := ec.n.getController().updateToStore(ec); err != nil {
        if err == datastore.ErrKeyModified {
            if err := store.GetObject(datastore.Key(ec.Key()...), ec); err != nil {
                return fmt.Errorf("could not update the kvobject to latest when trying to atomic add endpoint count: %v", err)
            }
            goto retry
        }
        return err
    }
    return nil
}
