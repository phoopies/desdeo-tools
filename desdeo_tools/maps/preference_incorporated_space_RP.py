from desdeo_tools.scalarization.GLIDE_II import (
    GLIDEBase,
    NIMBUS_GLIDE,
    reference_point_method_GLIDE,
)
from desdeo_tools.utilities import classification_to_reference_point
import numpy as np
from typing import Type, List, Union


class PreferenceIncorporatedSpaceError(Exception):
    "Raised when an error related to the preference incorporated space is encountered."


class __PreferenceIncorporatedSpace:
    def __init__(
        self,
        scalarizers: List[Type[GLIDEBase]],
        utopian: np.ndarray,
        nadir: np.ndarray,
        preference: dict,
        rho: float = 1e-6,
    ):
        self.scalarizers = scalarizers
        self.update_map(utopian=utopian, nadir=nadir, preference=preference, rho=rho)

    def update_map(
        self,
        utopian: np.ndarray,
        nadir: np.ndarray,
        preference: dict,
        scalarizers: List[Type[GLIDEBase]] = None,
        rho: float = 1e-6,
    ):
        if scalarizers is None:
            scalarizers = self.scalarizers
        else:
            self.scalarizers = scalarizers

        if utopian is not None:
            self.utopian = utopian
        if nadir is not None:
            self.nadir = nadir

        self.preference = preference

        self.initialized_scalarizers = [
            scalarizer(utopian=utopian, nadir=nadir, rho=rho)
            for scalarizer in scalarizers
        ]

        if "classifications" in preference.keys():
            self.classification_preference = preference
            self.RP_preference = classification_to_reference_point(
                preference, ideal=self.utopian, nadir=self.nadir
            )
        elif "reference point" in preference.keys():
            self.RP_preference = preference
            self.classification_preference = None

        self.preferences = []
        self.has_additional_constraints = False
        self.constrained_scalarizers = []

        for scalarizer in self.initialized_scalarizers:
            required_keys = scalarizer.required_keys.keys()

            if "reference point" in required_keys:
                self.requires_reference_point = True
                self.preferences.append(self.RP_preference)
            elif "classifications" in required_keys:
                self.requires_classifications = True
                if self.classification_preference is None:
                    raise PreferenceIncorporatedSpaceError(
                        f"A classification preference is required.\n"
                        f"Format of classification preference (dictionary): \n"
                        f"{scalarizer.required_keys}"
                    )
                self.preferences.append(self.classification_preference)
            else:
                raise PreferenceIncorporatedSpaceError(
                    f"Unknown scalarizing function encountered. Type: {type(scalarizer)}.\n"
                    f"Only scalarizing functions which require reference points "
                    f"or classification preferences are supported."
                    f"Current scalarizing functions requires: \n"
                    f"{scalarizer.required_keys}"
                )
            self.constrained_scalarizers.append(scalarizer.has_additional_constraints)
            self.has_additional_constraints = (
                self.has_additional_constraints or scalarizer.has_additional_constraints
            )

    def __call__(self, objective_vector: np.ndarray):
        mapped_vectors = np.zeros(
            (len(objective_vector), len(self.initialized_scalarizers))
        )
        for i, scalarizer in enumerate(self.initialized_scalarizers):
            mapped_vectors[:, i] = scalarizer(objective_vector, self.preferences[i])
        return mapped_vectors

    def evaluate_constraints(self, objective_vector: np.ndarray):
        if not self.has_additional_constraints:
            return None
        constraints = None
        for i, (scalarizer, has_constraints) in enumerate(
            zip(self.initialized_scalarizers, self.constrained_scalarizers)
        ):
            if not has_constraints:
                continue
            constraints = np.hstack(
                (
                    constraints,
                    scalarizer.evaluate_constraints(
                        objective_vector, self.preferences[i]
                    ),
                )
            )


class classificationPIS:
    """Implements the preference incorporated space mapping which uses the classification preference.

    Args:
        scalarizers (List[Type[GLIDEBase]]): Scalarizers to be used to create the PIS.
            Should include atleast one scalarizer. NIMBUS should not be included as it is added automatically.
        utopian (np.ndarray): The utopian point of the problem.
        nadir (np.ndarray): The nadir point of the problem.
        rho (float, optional): The augmentation factor used in the different scalarizers. Defaults to 1e-6.
    """

    def __init__(
        self,
        scalarizers: List[Type[GLIDEBase]],
        utopian: np.ndarray,
        nadir: np.ndarray,
        rho: float = 1e-6,
    ):
        self.nimbus: Union[NIMBUS_GLIDE, None] = None
        self.nimbus_copycat: Union[reference_point_method_GLIDE, None] = None
        self.scalarizers = scalarizers
        self.update_map(utopian=utopian, nadir=nadir, rho=rho)

    def update_map(
        self,
        utopian: np.ndarray,
        nadir: np.ndarray,
        scalarizers: List[Type[GLIDEBase]] = None,
        rho: float = 1e-6,
    ):
        if scalarizers is None:
            scalarizers = self.scalarizers
        else:
            self.scalarizers = scalarizers

        if utopian is not None:
            self.utopian = utopian
        if nadir is not None:
            self.nadir = nadir

        self.nimbus = NIMBUS_GLIDE(utopian=utopian, nadir=nadir)
        self.nimbus_copycat = reference_point_method_GLIDE(utopian=utopian, nadir=nadir)

        self.initialized_scalarizers = [
            scalarizer(utopian=utopian, nadir=nadir, rho=rho)
            for scalarizer in scalarizers
        ]
        self.has_additional_constraints = False

    def update_preference(self, preference: dict):

        self.preference = preference
        if "classifications" in preference.keys():
            self.classification_preference = preference
            self.RP_preference = classification_to_reference_point(
                preference, ideal=self.utopian, nadir=self.nadir
            )
        else:
            raise PreferenceIncorporatedSpaceError(
                "Classification preference expected."
            )

    def __call__(self, objective_vector: np.ndarray):

        # IOPIS/NIMBUS logic
        nimbus_obj = self.nimbus(
            objective_vector=objective_vector, preference=self.classification_preference
        )
        nimbus_constraint = self.nimbus.evaluate_constraints(
            objective_vector, self.classification_preference
        )
        feasible = np.all(nimbus_constraint > 0, axis=1)

        if not feasible.any():
            nimbus_optimal = objective_vector[nimbus_constraint.max(axis=1).argmax()]
        else:
            nimbus_obj[~feasible] = np.inf
            nimbus_optimal = objective_vector[nimbus_obj.argmin()]

        # IOPIS mapping
        mapped_vectors = np.zeros(
            (len(objective_vector), len(self.initialized_scalarizers) + 1)
        )

        mapped_vectors[:, 0] = self.nimbus_copycat(
            objective_vector=objective_vector,
            preference={"reference point": nimbus_optimal},
        )

        for i, scalarizer in enumerate(self.initialized_scalarizers):
            mapped_vectors[:, i + 1] = scalarizer(objective_vector, self.RP_preference)
        return mapped_vectors
