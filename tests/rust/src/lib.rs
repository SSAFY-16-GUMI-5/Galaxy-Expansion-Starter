#![forbid(unsafe_code)]

use galaxy_runner::{Borrow, CosmicSpec, Kind, Pool, StorageToken};

struct Slot {
    token: StorageToken,
    object: Option<CosmicSpec>,
    active: bool,
    issuance: u64,
}

pub struct FixturePool {
    slots: [Slot; 2],
}

pub struct Handle {
    index: usize,
    token: StorageToken,
    issuance: u64,
}

impl Default for FixturePool {
    fn default() -> Self {
        Self {
            slots: std::array::from_fn(|_| Slot {
                token: StorageToken::new(),
                object: None,
                active: false,
                issuance: 0,
            }),
        }
    }
}

impl Slot {
    fn owns(&self, handle: &Handle) -> bool {
        self.active && self.issuance == handle.issuance && self.token.same_storage(&handle.token)
    }
}

impl Pool for FixturePool {
    type Handle = Handle;

    fn acquire(&mut self, spec: &CosmicSpec) -> Result<Borrow<Handle>, String> {
        let (index, slot) = self
            .slots
            .iter_mut()
            .enumerate()
            .find(|(_, slot)| !slot.active)
            .ok_or("fixture pool is full")?;
        slot.issuance = slot
            .issuance
            .checked_add(1)
            .ok_or("borrow counter exhausted")?;
        if let Some(object) = &mut slot.object {
            object.clone_from(spec);
        } else {
            slot.object = Some(spec.clone());
        }
        slot.active = true;
        Ok(Borrow {
            storage: slot.token.clone(),
            handle: Handle {
                index,
                token: slot.token.clone(),
                issuance: slot.issuance,
            },
        })
    }

    fn snapshot(&self, handle: &Handle) -> Result<CosmicSpec, String> {
        let slot = &self.slots[handle.index];
        if !slot.owns(handle) {
            return Err("foreign or expired fixture handle".into());
        }
        Ok(slot.object.as_ref().expect("active object").clone())
    }

    fn release(&mut self, handle: Handle) -> Result<(), String> {
        let slot = &mut self.slots[handle.index];
        if !slot.owns(&handle) {
            return Err("foreign or expired fixture handle".into());
        }
        slot.active = false;
        Ok(())
    }
}

pub fn aurora() -> CosmicSpec {
    CosmicSpec {
        name: "오로라 ✨".into(),
        kind: Kind::Star,
        color: "#5dcaff".into(),
        size: 1.2,
    }
}

pub fn nova() -> CosmicSpec {
    CosmicSpec {
        name: "다시 태어난 별".into(),
        kind: Kind::Planet,
        color: "#a78bfa".into(),
        size: 1.6,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reborrow_keeps_actual_storage_and_reinitializes_every_field() {
        let mut pool = FixturePool::default();
        let first = pool.acquire(&aurora()).unwrap();
        let address = std::ptr::from_ref(pool.slots[0].object.as_ref().unwrap());
        let stale = Handle {
            index: first.handle.index,
            token: first.handle.token.clone(),
            issuance: first.handle.issuance,
        };
        let old = pool.snapshot(&first.handle).unwrap();
        pool.release(first.handle).unwrap();
        assert!(pool.snapshot(&stale).is_err());

        let second = pool.acquire(&nova()).unwrap();
        assert_eq!(
            address,
            std::ptr::from_ref(pool.slots[0].object.as_ref().unwrap())
        );
        assert!(first.storage.same_storage(&second.storage));
        assert!(pool.release(stale).is_err());
        assert_eq!(pool.snapshot(&second.handle).unwrap(), nova());
        assert_eq!(old, aurora());
    }

    #[test]
    fn active_storage_is_distinct_and_foreign_returns_do_not_free_it() {
        let mut pool = FixturePool::default();
        let first = pool.acquire(&aurora()).unwrap();
        let second = pool.acquire(&aurora()).unwrap();
        assert!(!first.storage.same_storage(&second.storage));
        let foreign = FixturePool::default().acquire(&aurora()).unwrap();
        assert!(pool.release(foreign.handle).is_err());
        assert!(pool.acquire(&aurora()).is_err());
        pool.release(second.handle).unwrap();
        assert_eq!(pool.snapshot(&first.handle).unwrap(), aurora());
    }
}
