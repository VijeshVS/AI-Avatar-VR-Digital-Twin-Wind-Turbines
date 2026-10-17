using UnityEngine;

namespace Vrar.Environment
{
    /// <summary>
    /// Keeps the livestock out of itself and out of the trees.
    ///
    /// The animals are kinematic — no rigidbodies, no colliders, transforms only —
    /// because each body is nineteen separate cubes that have to move as one animal
    /// and a rigidbody would drag every cube into its own physics body. Solidity is
    /// therefore a constraint problem rather than a physics one, and it lives here
    /// rather than inside <see cref="Animal"/> so it runs once per frame instead of
    /// once per animal, with a deterministic order that does not depend on which
    /// animal's Update happened to fire first.
    ///
    /// In LateUpdate so every animal has finished walking before the overlaps are
    /// projected out: a solver that ran in Update would resolve against positions
    /// some animals had already abandoned and leave a frame of interpenetration.
    /// </summary>
    [DisallowMultipleComponent]
    public sealed class HerdSolver : MonoBehaviour
    {
        /// <summary>
        /// Projection passes per frame. One pass resolves a pair cleanly, but a
        /// cluster of animals all pushing at once needs a few rounds before the
        /// constraint set is satisfied everywhere. Three is comfortably more than
        /// the herd sizes here need and still well under a millisecond.
        /// </summary>
        private const int Passes = 3;

        private void LateUpdate()
        {
            var herd = Animal.Active;
            Animal.Prune();

            int count = herd.Count;
            if (count == 0)
            {
                return;
            }

            for (int i = 0; i < count; i++)
            {
                herd[i].ConstrainToRange();
                herd[i].ResolveAgainstProps();
            }

            for (int pass = 0; pass < Passes; pass++)
            {
                for (int i = 0; i < count; i++)
                {
                    for (int j = i + 1; j < count; j++)
                    {
                        Animal.Separate(herd[i], herd[j]);
                    }
                }

                // Props are immovable, so they get the last word within each pass and
                // a tree can never end up displaced to make room for a herd.
                for (int i = 0; i < count; i++)
                {
                    herd[i].ResolveAgainstProps();
                }
            }

            for (int i = 0; i < count; i++)
            {
                herd[i].Reground();
            }
        }
    }
}